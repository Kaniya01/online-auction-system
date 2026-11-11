from datetime import timedelta
from decimal import Decimal
import hashlib
import hmac
import json
from unittest.mock import Mock, patch

from django.contrib.auth.models import User
from django.core.management import call_command
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.test import override_settings
from django.core import mail
from django.urls import reverse
from django.utils import timezone

from .browse_views import update_auction_status
from .models import Auction, AuctionReport, Bid, Notification, Product, Profile, Watchlist, RecentlyViewedAuction, Payment, PaymentAttempt, PaymentWebhookEvent


class AuctionFlowTests(TestCase):
    def setUp(self):
        self.seller = User.objects.create_user('seller', password='test-password-123')
        self.bidder = User.objects.create_user('bidder', password='test-password-123')
        self.other_bidder = User.objects.create_user('other', password='test-password-123')
        Profile.objects.update_or_create(
            user=self.seller,
            defaults={'full_name': 'Seller', 'phone_number': '1234567'},
        )
        Profile.objects.update_or_create(
            user=self.bidder,
            defaults={'full_name': 'Bidder', 'phone_number': '1234567'},
        )
        Profile.objects.update_or_create(
            user=self.other_bidder,
            defaults={'full_name': 'Other', 'phone_number': '1234567'},
        )

        now = timezone.now()
        self.product = Product.objects.create(
            seller=self.seller,
            name='Camera',
            category='Electronics',
            description='Used camera',
            condition='GOOD',
            starting_price=Decimal('100.00'),
        )
        self.auction = Auction.objects.create(
            product=self.product,
            start_time=now - timedelta(hours=1),
            end_time=now + timedelta(hours=1),
            starting_bid=Decimal('100.00'),
            current_highest_bid=Decimal('100.00'),
            status='ACTIVE',
        )

    def test_valid_bid_updates_winner_and_notifies_seller(self):
        self.client.force_login(self.bidder)

        response = self.client.post(
            reverse('place_bid', args=[self.auction.id]),
            {'amount': '125.50'},
        )

        self.assertRedirects(response, reverse('auction_detail', args=[self.auction.id]))
        self.auction.refresh_from_db()
        self.assertEqual(self.auction.current_highest_bid, Decimal('125.50'))
        self.assertEqual(self.auction.highest_bidder, self.bidder)
        self.assertEqual(Bid.objects.filter(auction=self.auction).count(), 1)
        self.assertTrue(Notification.objects.filter(user=self.seller, notification_type='BID').exists())

    def test_outbid_bidder_receives_notice(self):
        Bid.objects.create(auction=self.auction, buyer=self.bidder, amount=Decimal('110.00'))
        self.auction.current_highest_bid = Decimal('110.00')
        self.auction.highest_bidder = self.bidder
        self.auction.save(update_fields=['current_highest_bid', 'highest_bidder'])
        self.client.force_login(self.other_bidder)

        self.client.post(reverse('place_bid', args=[self.auction.id]), {'amount': '120.00'})

        self.assertTrue(Notification.objects.filter(
            user=self.bidder,
            notification_type='OUTBID',
        ).exists())

    def test_seller_cannot_bid_on_own_auction(self):
        self.client.force_login(self.seller)

        self.client.post(reverse('place_bid', args=[self.auction.id]), {'amount': '150.00'})

        self.assertFalse(Bid.objects.filter(auction=self.auction).exists())

    def test_invalid_bid_amounts_are_rejected(self):
        self.client.force_login(self.bidder)

        for amount in ('100', 'NaN', 'Infinity', '101.001', '99999999999'):
            with self.subTest(amount=amount):
                self.client.post(reverse('place_bid', args=[self.auction.id]), {'amount': amount})

        self.assertFalse(Bid.objects.filter(auction=self.auction).exists())

    def test_closing_auction_notifies_winner_once(self):
        Bid.objects.create(auction=self.auction, buyer=self.bidder, amount=Decimal('125.00'))
        self.auction.end_time = timezone.now() - timedelta(minutes=1)
        self.auction.save(update_fields=['end_time'])

        update_auction_status(self.auction)
        update_auction_status(self.auction)

        self.auction.refresh_from_db()
        self.assertEqual(self.auction.status, 'CLOSED')
        self.assertEqual(Notification.objects.filter(
            user=self.bidder,
            notification_type='WINNER',
        ).count(), 1)

    def test_buyer_and_seller_pages_render(self):
        self.client.force_login(self.bidder)
        buyer_urls = (
            reverse('dashboard'),
            reverse('browse_auctions'),
            reverse('auction_detail', args=[self.auction.id]),
            reverse('my_bids'),
            reverse('profile'),
        )
        for url in buyer_urls:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 200)

        self.client.force_login(self.seller)
        seller_urls = (
            reverse('seller_products'),
            reverse('seller_auctions'),
        )
        for url in seller_urls:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 200)


class NotificationViewTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('reader', password='test-password-123')
        self.other_user = User.objects.create_user('other-reader', password='test-password-123')
        self.notification = Notification.objects.create(
            user=self.user,
            title='Test update',
            message='Auction activity',
            notification_type='BID',
        )
        self.client.force_login(self.user)

    def test_notification_can_be_marked_read(self):
        response = self.client.post(reverse(
            'mark_notification_read', args=[self.notification.id]
        ))

        self.assertRedirects(response, reverse('notifications'))
        self.notification.refresh_from_db()
        self.assertTrue(self.notification.is_read)

    def test_user_cannot_mark_another_users_notification_read(self):
        self.notification.user = self.other_user
        self.notification.save(update_fields=['user'])

        response = self.client.post(reverse(
            'mark_notification_read', args=[self.notification.id]
        ))

        self.assertEqual(response.status_code, 404)
        self.notification.refresh_from_db()
        self.assertFalse(self.notification.is_read)

    def test_read_actions_require_post(self):
        response = self.client.get(reverse('mark_all_notifications_read'))

        self.assertEqual(response.status_code, 302)
        self.notification.refresh_from_db()
        self.assertFalse(self.notification.is_read)


class WatchlistTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user('watch-owner', password='test-password-123')
        self.buyer = User.objects.create_user('watch-buyer', password='test-password-123')
        self.other_buyer = User.objects.create_user('watch-other', password='test-password-123')
        now = timezone.now()
        self.product = Product.objects.create(
            seller=self.owner,
            name='Watchlist Camera',
            category='Electronics',
            description='A camera to save',
            condition='GOOD',
            starting_price=Decimal('80.00'),
        )
        self.auction = Auction.objects.create(
            product=self.product,
            start_time=now - timedelta(minutes=30),
            end_time=now + timedelta(hours=2),
            starting_bid=Decimal('80.00'),
            current_highest_bid=Decimal('80.00'),
            status='ACTIVE',
        )

    def test_authenticated_user_can_add_auction(self):
        self.client.force_login(self.buyer)
        response = self.client.post(reverse('add_to_watchlist', args=[self.auction.id]))
        self.assertRedirects(response, reverse('auction_detail', args=[self.auction.id]))
        self.assertTrue(Watchlist.objects.filter(user=self.buyer, auction=self.auction).exists())

    def test_add_is_idempotent_and_database_constraint_prevents_duplicates(self):
        self.client.force_login(self.buyer)
        url = reverse('add_to_watchlist', args=[self.auction.id])
        self.client.post(url)
        self.client.post(url)
        self.assertEqual(Watchlist.objects.filter(user=self.buyer, auction=self.auction).count(), 1)
        with self.assertRaises(IntegrityError), transaction.atomic():
            Watchlist.objects.create(user=self.buyer, auction=self.auction)

    def test_authenticated_user_can_remove_saved_auction(self):
        entry = Watchlist.objects.create(user=self.buyer, auction=self.auction)
        self.client.force_login(self.buyer)
        response = self.client.post(reverse('remove_from_watchlist', args=[self.auction.id]))
        self.assertRedirects(response, reverse('my_watchlist'))
        self.assertFalse(Watchlist.objects.filter(pk=entry.pk).exists())

    def test_watchlist_actions_and_page_require_authentication(self):
        for url in (
            reverse('my_watchlist'),
            reverse('add_to_watchlist', args=[self.auction.id]),
            reverse('remove_from_watchlist', args=[self.auction.id]),
        ):
            with self.subTest(url=url):
                self.assertRedirects(self.client.get(url), f'{reverse("login")}?next={url}')

    def test_watchlist_mutations_require_csrf_token(self):
        csrf_client = self.client_class(enforce_csrf_checks=True)
        csrf_client.force_login(self.buyer)
        response = csrf_client.post(reverse('add_to_watchlist', args=[self.auction.id]))
        self.assertEqual(response.status_code, 403)
        self.assertFalse(Watchlist.objects.filter(user=self.buyer, auction=self.auction).exists())

    def test_users_only_see_and_remove_their_own_entries(self):
        entry = Watchlist.objects.create(user=self.buyer, auction=self.auction)
        self.client.force_login(self.other_buyer)
        page = self.client.get(reverse('my_watchlist'))
        self.assertNotContains(page, self.auction.product.name)
        self.client.post(reverse('remove_from_watchlist', args=[self.auction.id]))
        self.assertTrue(Watchlist.objects.filter(pk=entry.pk, user=self.buyer).exists())

    def test_watchlist_page_shows_saved_auction_and_empty_state(self):
        self.client.force_login(self.buyer)
        empty_page = self.client.get(reverse('my_watchlist'))
        self.assertContains(empty_page, 'Your watchlist is empty')
        Watchlist.objects.create(user=self.buyer, auction=self.auction)
        page = self.client.get(reverse('my_watchlist'))
        self.assertContains(page, 'Watchlist Camera')
        self.assertContains(page, '₹80.00')
        self.assertContains(page, 'View Auction')

    def test_ended_saved_auction_remains_rendered_and_can_be_removed(self):
        self.auction.end_time = timezone.now() - timedelta(minutes=1)
        self.auction.save(update_fields=['end_time'])
        entry = Watchlist.objects.create(user=self.buyer, auction=self.auction)
        self.client.force_login(self.buyer)
        page = self.client.get(reverse('my_watchlist'))
        self.assertContains(page, 'Watchlist Camera')
        self.assertContains(page, 'Closed')
        response = self.client.post(reverse('remove_from_watchlist', args=[self.auction.id]))
        self.assertRedirects(response, reverse('my_watchlist'))
        self.assertFalse(Watchlist.objects.filter(pk=entry.pk).exists())

    def test_cancelled_and_deleted_auctions_do_not_break_watchlist(self):
        entry = Watchlist.objects.create(user=self.buyer, auction=self.auction)
        self.auction.status = 'CANCELLED'
        self.auction.save(update_fields=['status'])
        self.client.force_login(self.buyer)
        page = self.client.get(reverse('my_watchlist'))
        self.assertContains(page, 'Cancelled')
        self.assertTrue(Watchlist.objects.filter(pk=entry.pk).exists())

        self.auction.delete()
        empty_page = self.client.get(reverse('my_watchlist'))
        self.assertContains(empty_page, 'Your watchlist is empty')

    def test_owner_cannot_add_own_auction_and_ended_auction_is_ineligible(self):
        self.client.force_login(self.owner)
        self.client.post(reverse('add_to_watchlist', args=[self.auction.id]))
        self.assertFalse(Watchlist.objects.filter(user=self.owner, auction=self.auction).exists())

        self.auction.end_time = timezone.now() - timedelta(minutes=1)
        self.auction.save(update_fields=['end_time'])
        self.client.force_login(self.buyer)
        self.client.post(reverse('add_to_watchlist', args=[self.auction.id]))
        self.assertFalse(Watchlist.objects.filter(user=self.buyer, auction=self.auction).exists())

class AccountAndSellerFlowTests(TestCase):
    def setUp(self):
        self.seller = User.objects.create_user('seller-flow', password='test-password-123')
        self.other_user = User.objects.create_user('other-flow', password='test-password-123')
        Profile.objects.update_or_create(
            user=self.seller,
            defaults={'full_name': 'Seller Name', 'phone_number': '1234567'},
        )
        Profile.objects.update_or_create(
            user=self.other_user,
            defaults={'full_name': 'Other Name', 'phone_number': '7654321'},
        )

    def test_navigation_tracks_session_mode_without_changing_profile_role(self):
        self.client.force_login(self.seller)

        buyer_page = self.client.get(reverse('dashboard'))
        self.assertContains(buyer_page, 'Browse Auctions')
        self.assertContains(buyer_page, 'My Watchlist')
        self.assertNotContains(buyer_page, 'My Products')
        self.assertNotContains(buyer_page, 'Administration')

        switched = self.client.get(reverse('switch_mode', args=['SELLER']))
        self.assertRedirects(switched, reverse('dashboard'))
        self.assertEqual(self.client.session['mode'], 'SELLER')
        self.seller.profile.refresh_from_db()
        self.assertEqual(self.seller.profile.role, 'BUYER')

        seller_page = self.client.get(reverse('dashboard'))
        self.assertContains(seller_page, 'My Products')
        self.assertContains(seller_page, 'Scheduled Auctions')
        self.assertNotContains(seller_page, 'My Watchlist')

    def test_admin_navigation_and_urls_require_staff_access(self):
        self.client.force_login(self.other_user)
        page = self.client.get(reverse('dashboard'))
        self.assertNotContains(page, 'Administration')
        self.assertNotContains(page, 'Manage Users')
        self.assertEqual(self.client.get(reverse('admin:index')).status_code, 302)
        self.assertEqual(
            self.client.get(reverse('admin:auth_user_changelist')).status_code,
            302,
        )

        administrator = User.objects.create_superuser(
            'navigation-admin',
            'admin@example.com',
            'test-password-123',
        )
        self.client.force_login(administrator)
        admin_page = self.client.get(reverse('dashboard'))
        self.assertContains(admin_page, 'Admin Overview')
        self.assertContains(admin_page, 'Manage Users')
        self.assertContains(admin_page, 'Manage Products')
        self.assertContains(admin_page, 'Platform Analytics')
        self.assertEqual(self.client.get(reverse('admin:index')).status_code, 200)

    def test_profile_is_created_for_accounts_created_outside_registration(self):
        staff_user = User.objects.create_user('created-outside-form')

        self.assertEqual(staff_user.profile.full_name, 'created-outside-form')
        self.assertEqual(staff_user.profile.phone_number, '')

    def test_registration_creates_profile_and_welcome_notification(self):
        response = self.client.post(reverse('register'), {
            'username': 'new-buyer',
            'email': 'buyer@example.com',
            'password': 'River!Stone-2026',
            'confirm_password': 'River!Stone-2026',
            'full_name': 'New Buyer',
            'phone_number': '9876543210',
        }, follow=True)

        self.assertContains(response, 'Account created successfully!')
        new_user = User.objects.get(username='new-buyer')
        self.assertEqual(new_user.profile.full_name, 'New Buyer')
        self.assertTrue(Notification.objects.filter(
            user=new_user,
            notification_type='REGISTRATION',
        ).exists())

    def test_success_messages_are_consumed_on_redirect_pages_before_logout(self):
        self.client.force_login(self.seller)

        product_response = self.client.post(reverse('add_product'), {
            'name': 'Flash Message Item',
            'category': 'Home',
            'description': 'A product for the redirect message test.',
            'condition': 'GOOD',
            'starting_price': '50.00',
        }, follow=True)
        self.assertContains(product_response, 'Product added successfully!')
        self.assertNotContains(product_response, 'Auction created successfully!')
        product = Product.objects.get(name='Flash Message Item')

        start_time = timezone.localtime(timezone.now() + timedelta(hours=2))
        end_time = timezone.localtime(timezone.now() + timedelta(hours=3))
        auction_response = self.client.post(
            reverse('create_auction', args=[product.id]),
            {
                'start_time': start_time.strftime('%Y-%m-%dT%H:%M'),
                'end_time': end_time.strftime('%Y-%m-%dT%H:%M'),
            },
            follow=True,
        )
        self.assertContains(auction_response, 'Auction created successfully!')
        self.assertNotContains(auction_response, 'Product added successfully!')

        login_before_logout = self.client.get(reverse('login'))
        self.assertNotContains(login_before_logout, 'Product added successfully!')
        self.assertNotContains(login_before_logout, 'Auction created successfully!')
        self.assertNotContains(login_before_logout, 'You have been logged out.')

        logout_response = self.client.get(reverse('logout'), follow=True)
        self.assertContains(logout_response, 'You have been logged out.')
        self.assertNotContains(logout_response, 'Product added successfully!')
        self.assertNotContains(logout_response, 'Auction created successfully!')

    def test_registration_rejects_weak_password(self):
        response = self.client.post(reverse('register'), {
            'username': 'weak-password-user',
            'email': 'weak@example.com',
            'password': 'password123',
            'confirm_password': 'password123',
            'full_name': 'Weak Password',
            'phone_number': '9876543210',
        })

        self.assertEqual(response.status_code, 200)
        self.assertFalse(User.objects.filter(username='weak-password-user').exists())

    def test_login_uses_local_next_url_and_rejects_external_redirect(self):
        self.client.post(reverse('register'), {
            'username': 'login-user',
            'email': 'login@example.com',
            'password': 'River!Stone-2026',
            'confirm_password': 'River!Stone-2026',
            'full_name': 'Login User',
            'phone_number': '9876543210',
        })

        local_response = self.client.post(reverse('login'), {
            'username': 'login-user',
            'password': 'River!Stone-2026',
            'next': '/my-bids/',
        })
        self.assertRedirects(local_response, '/my-bids/', fetch_redirect_response=False)
        self.client.logout()

        external_response = self.client.post(reverse('login'), {
            'username': 'login-user',
            'password': 'River!Stone-2026',
            'next': 'https://example.invalid/steal-session',
        })
        self.assertRedirects(external_response, reverse('dashboard'), fetch_redirect_response=False)

    def test_profile_edit_updates_only_logged_in_users_profile(self):
        self.client.force_login(self.seller)

        response = self.client.post(reverse('edit_profile'), {
            'full_name': 'Updated Seller',
            'phone_number': '1112223333',
        })

        self.assertRedirects(response, reverse('dashboard'))
        self.seller.profile.refresh_from_db()
        self.assertEqual(self.seller.profile.full_name, 'Updated Seller')
        self.assertEqual(
            Profile.objects.get(user=self.other_user).full_name,
            'Other Name',
        )

    def test_seller_can_add_product_and_is_assigned_as_owner(self):
        self.client.force_login(self.seller)

        response = self.client.post(reverse('add_product'), {
            'name': 'Vintage Radio',
            'category': 'Electronics',
            'description': 'Working radio',
            'condition': 'GOOD',
            'starting_price': '50.00',
        })

        product = Product.objects.get(name='Vintage Radio')
        self.assertEqual(product.seller, self.seller)
        self.assertRedirects(response, reverse('create_auction', args=[product.id]))

    def test_product_and_auction_edit_are_owner_scoped(self):
        product = Product.objects.create(
            seller=self.seller,
            name='Owned Item',
            category='Home',
            description='Description',
            condition='GOOD',
            starting_price=Decimal('25.00'),
        )
        auction = Auction.objects.create(
            product=product,
            start_time=timezone.now() + timedelta(days=1),
            end_time=timezone.now() + timedelta(days=2),
            starting_bid=Decimal('25.00'),
        )
        self.client.force_login(self.other_user)

        self.assertEqual(self.client.get(reverse('edit_product', args=[product.id])).status_code, 404)
        self.assertEqual(self.client.get(reverse('edit_auction', args=[auction.id])).status_code, 404)
        self.assertEqual(self.client.get(reverse('create_auction', args=[product.id])).status_code, 404)

    def test_seller_can_schedule_a_future_auction(self):
        product = Product.objects.create(
            seller=self.seller,
            name='Scheduled Item',
            category='Home',
            description='Description',
            condition='GOOD',
            starting_price=Decimal('35.00'),
        )
        start = timezone.localtime(timezone.now() + timedelta(hours=2))
        end = timezone.localtime(timezone.now() + timedelta(hours=3))
        self.client.force_login(self.seller)

        response = self.client.post(reverse('create_auction', args=[product.id]), {
            'start_time': start.strftime('%Y-%m-%dT%H:%M'),
            'end_time': end.strftime('%Y-%m-%dT%H:%M'),
        })

        auction = Auction.objects.get(product=product)
        self.assertEqual(auction.status, 'SCHEDULED')
        self.assertEqual(auction.starting_bid, product.starting_price)
        self.assertRedirects(response, reverse('dashboard'))
        self.assertTrue(Notification.objects.filter(
            user=self.seller,
            notification_type='AUCTION_CREATED',
        ).exists())


class AuctionScheduleEditTests(TestCase):
    def setUp(self):
        self.seller = User.objects.create_user('schedule-edit-seller', password='test-password-123')
        self.other_seller = User.objects.create_user('schedule-edit-other', password='test-password-123')
        self.bidder = User.objects.create_user('schedule-edit-bidder', password='test-password-123')
        self.product = Product.objects.create(
            seller=self.seller,
            name='Schedule Edit Product',
            category='Home',
            description='Schedule editing test',
            condition='GOOD',
            starting_price=Decimal('50.00'),
        )
        self.auction = self.make_auction(self.product)
        self.client.force_login(self.seller)

    def make_auction(self, product, *, status='SCHEDULED', start=None, end=None):
        now = timezone.now()
        return Auction.objects.create(
            product=product,
            start_time=start or now + timedelta(days=1),
            end_time=end or now + timedelta(days=2),
            starting_bid=product.starting_price,
            current_highest_bid=product.starting_price,
            status=status,
        )

    def post_schedule(self, auction=None, *, start=None, end=None):
        auction = auction or self.auction
        start = start or timezone.localtime(timezone.now() + timedelta(days=3))
        end = end or timezone.localtime(timezone.now() + timedelta(days=4))
        return self.client.post(reverse('edit_auction', args=[auction.pk]), {
            'start_time': start.strftime('%Y-%m-%dT%H:%M'),
            'end_time': end.strftime('%Y-%m-%dT%H:%M'),
        })

    def test_seller_can_edit_unbid_scheduled_auction_schedule_only(self):
        original_starting_bid = self.auction.starting_bid
        original_highest_bid = self.auction.current_highest_bid
        start = timezone.localtime(timezone.now() + timedelta(days=3))
        end = timezone.localtime(timezone.now() + timedelta(days=4))

        response = self.post_schedule(start=start, end=end)

        self.assertRedirects(response, reverse('seller_auctions'))
        self.auction.refresh_from_db()
        self.assertAlmostEqual(self.auction.start_time.timestamp(), start.timestamp(), delta=60)
        self.assertAlmostEqual(self.auction.end_time.timestamp(), end.timestamp(), delta=60)
        self.assertEqual(self.auction.status, 'SCHEDULED')
        self.assertEqual(self.auction.starting_bid, original_starting_bid)
        self.assertEqual(self.auction.current_highest_bid, original_highest_bid)
        self.assertIsNone(self.auction.highest_bidder_id)
        self.assertFalse(Bid.objects.filter(auction=self.auction).exists())
        self.assertFalse(Payment.objects.filter(auction=self.auction).exists())

    def test_other_seller_cannot_edit_auction(self):
        self.client.force_login(self.other_seller)
        response = self.client.get(reverse('edit_auction', args=[self.auction.pk]))
        self.assertEqual(response.status_code, 404)
        response = self.post_schedule()
        self.assertEqual(response.status_code, 404)

    def test_auction_with_bid_history_cannot_be_edited(self):
        original_start = self.auction.start_time
        Bid.objects.create(auction=self.auction, buyer=self.bidder, amount=Decimal('55.00'))
        response = self.post_schedule()
        self.assertRedirects(response, reverse('seller_auctions'))
        self.auction.refresh_from_db()
        self.assertEqual(self.auction.start_time, original_start)
        self.assertEqual(Bid.objects.filter(auction=self.auction).count(), 1)

    def test_active_closed_completed_and_cancelled_auctions_cannot_be_edited(self):
        now = timezone.now()
        cases = (
            ('ACTIVE', now - timedelta(minutes=5), now + timedelta(hours=1)),
            ('CLOSED', now - timedelta(hours=2), now - timedelta(hours=1)),
            ('SCHEDULED', now + timedelta(days=1), now - timedelta(hours=1)),
            ('COMPLETED', now + timedelta(days=1), now + timedelta(days=2)),
            ('CANCELLED', now + timedelta(days=1), now + timedelta(days=2)),
        )
        for index, (status, start, end) in enumerate(cases):
            with self.subTest(status=status):
                product = Product.objects.create(
                    seller=self.seller,
                    name=f'Blocked schedule {index}',
                    category='Home',
                    description='Blocked schedule test',
                    condition='GOOD',
                    starting_price=Decimal('50.00'),
                )
                auction = self.make_auction(product, status=status, start=start, end=end)
                response = self.post_schedule(auction)
                self.assertRedirects(response, reverse('seller_auctions'))

    def test_payment_record_or_attempt_blocks_schedule_edits(self):
        original_start = self.auction.start_time
        payment = Payment.objects.create(
            auction=self.auction,
            buyer=self.bidder,
            amount=Decimal('50.00'),
            payment_status='UNPAID',
        )
        PaymentAttempt.objects.create(payment=payment, attempt_number=1, status='FAILED')

        response = self.post_schedule()

        self.assertRedirects(response, reverse('seller_auctions'))
        self.auction.refresh_from_db()
        self.assertEqual(self.auction.start_time, original_start)
        self.assertTrue(Payment.objects.filter(pk=payment.pk).exists())
        self.assertEqual(payment.attempts.count(), 1)

    def test_invalid_start_and_end_times_are_rejected(self):
        past = timezone.localtime(timezone.now() - timedelta(hours=1))
        later = timezone.localtime(timezone.now() + timedelta(hours=1))
        response = self.post_schedule(start=past, end=later)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Auction start time must be in the future.')

        future = timezone.localtime(timezone.now() + timedelta(days=2))
        earlier = timezone.localtime(timezone.now() + timedelta(days=1))
        response = self.post_schedule(start=future, end=earlier)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'End time must be after start time.')

    def test_status_is_refreshed_before_edit_eligibility_is_checked(self):
        now = timezone.now()
        self.auction.start_time = now - timedelta(minutes=1)
        self.auction.end_time = now + timedelta(hours=1)
        self.auction.status = 'SCHEDULED'
        self.auction.save(update_fields=['start_time', 'end_time', 'status'])

        response = self.client.get(reverse('edit_auction', args=[self.auction.pk]))

        self.assertRedirects(response, reverse('seller_auctions'))
        self.auction.refresh_from_db()
        self.assertEqual(self.auction.status, 'ACTIVE')

    def test_seller_list_hides_edit_action_for_ineligible_auction(self):
        Bid.objects.create(auction=self.auction, buyer=self.bidder, amount=Decimal('55.00'))
        response = self.client.get(reverse('seller_auctions'))
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.context['auctions'][0].can_edit_schedule)


class PhaseThreeSellerFeatureTests(TestCase):
    def setUp(self):
        self.seller = User.objects.create_user('phase3-seller', password='test-password-123')
        self.other_seller = User.objects.create_user('phase3-other', password='test-password-123')
        self.bidder = User.objects.create_user(
            'phase3-bidder',
            email='private-bidder@example.test',
            password='test-password-123',
        )
        self.second_bidder = User.objects.create_user('phase3-bidder-two', password='test-password-123')
        self.client.force_login(self.seller)
        self.product = Product.objects.create(
            seller=self.seller,
            name='Phase 3 Camera',
            category='Electronics',
            description='A seller feature test product',
            condition='GOOD',
            starting_price=Decimal('100.00'),
        )
        now = timezone.now()
        self.auction = Auction.objects.create(
            product=self.product,
            start_time=now - timedelta(hours=1),
            end_time=now + timedelta(hours=1),
            starting_bid=Decimal('100.00'),
            current_highest_bid=Decimal('100.00'),
            status='ACTIVE',
        )

    def make_auction(self, seller, name, *, status='ACTIVE', ended=False, price='50.00'):
        product = Product.objects.create(
            seller=seller,
            name=name,
            category='Collectibles',
            description='Test item',
            condition='GOOD',
            starting_price=Decimal(price),
        )
        now = timezone.now()
        return Auction.objects.create(
            product=product,
            start_time=now - timedelta(hours=2),
            end_time=now - timedelta(minutes=1) if ended else now + timedelta(hours=2),
            starting_bid=Decimal(price),
            current_highest_bid=Decimal(price),
            status=status,
        )

    def test_received_bids_are_owner_scoped_and_mark_only_leading_bid(self):
        first = Bid.objects.create(auction=self.auction, buyer=self.bidder, amount=Decimal('110.00'))
        leading = Bid.objects.create(auction=self.auction, buyer=self.second_bidder, amount=Decimal('125.00'))
        self.auction.current_highest_bid = leading.amount
        self.auction.highest_bidder = self.second_bidder
        self.auction.save(update_fields=['current_highest_bid', 'highest_bidder'])
        other_auction = self.make_auction(self.other_seller, 'Private seller item')
        Bid.objects.create(auction=other_auction, buyer=self.bidder, amount=Decimal('60.00'))

        response = self.client.get(reverse('received_bids'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'phase3-bidder')
        self.assertNotContains(response, 'private-bidder@example.test')
        self.assertNotContains(response, 'Private seller item')
        rows = {bid.pk: bid for bid in response.context['bids']}
        self.assertFalse(rows[first.pk].is_leading)
        self.assertTrue(rows[leading.pk].is_leading)

    def test_received_bids_empty_state_and_filters(self):
        self.assertContains(self.client.get(reverse('received_bids')), 'No bids found')
        bid = Bid.objects.create(auction=self.auction, buyer=self.bidder, amount=Decimal('105.00'))
        response = self.client.get(reverse('received_bids'), {'auction': self.auction.pk, 'status': 'ACTIVE'})
        self.assertContains(response, str(bid.amount))
        self.assertEqual(len(response.context['bids']), 1)
        self.assertEqual(
            self.client.get(reverse('received_bids'), {'auction': self.auction.pk + 999}).context['page_obj'].paginator.count,
            1,
        )

    def test_winners_show_winning_bid_and_no_winner_but_exclude_cancelled(self):
        self.auction.end_time = timezone.now() - timedelta(minutes=1)
        self.auction.save(update_fields=['end_time'])
        winning_bid = Bid.objects.create(auction=self.auction, buyer=self.bidder, amount=Decimal('140.00'))
        no_bid_auction = self.make_auction(self.seller, 'No bid item', ended=True)
        cancelled = self.make_auction(self.seller, 'Cancelled item', status='CANCELLED')

        response = self.client.get(reverse('seller_winners'))
        self.assertContains(response, self.bidder.username)
        self.assertContains(response, str(winning_bid.amount))
        self.assertContains(response, 'No bid item')
        self.assertContains(response, 'No winner')
        self.assertNotContains(response, 'Cancelled item')
        self.assertContains(response, reverse('received_bids') + f'?auction={self.auction.pk}')

    def test_winner_page_is_scoped_to_owner(self):
        foreign = self.make_auction(self.other_seller, 'Other seller winner', ended=True)
        Bid.objects.create(auction=foreign, buyer=self.bidder, amount=Decimal('80.00'))
        self.assertNotContains(self.client.get(reverse('seller_winners')), 'Other seller winner')

    def test_unused_product_is_deleted_but_auction_product_is_archived(self):
        unused = Product.objects.create(
            seller=self.seller, name='Unused', category='Home', description='Unused',
            condition='GOOD', starting_price=Decimal('10.00'),
        )
        self.client.post(reverse('manage_product', args=[unused.pk]))
        self.assertFalse(Product.objects.filter(pk=unused.pk).exists())

        self.client.post(reverse('manage_product', args=[self.product.pk]))
        self.product.refresh_from_db()
        self.assertTrue(self.product.is_archived)
        self.assertTrue(Auction.objects.filter(pk=self.auction.pk).exists())
        self.assertEqual(self.client.get(reverse('auction_detail', args=[self.auction.pk])).status_code, 200)

    def test_archived_product_cannot_create_auction_and_product_mutations_are_owner_scoped(self):
        archived_product = Product.objects.create(
            seller=self.seller, name='Archived unused', category='Home', description='Archived',
            condition='GOOD', starting_price=Decimal('12.00'), is_archived=True,
        )
        response = self.client.get(reverse('create_auction', args=[archived_product.pk]))
        self.assertRedirects(response, reverse('seller_products'))
        self.assertFalse(Auction.objects.filter(product=archived_product).exists())

        other_product = Product.objects.create(
            seller=self.other_seller, name='Other product', category='Home', description='Private',
            condition='GOOD', starting_price=Decimal('10.00'),
        )
        response = self.client.post(reverse('manage_product', args=[other_product.pk]))
        self.assertEqual(response.status_code, 404)
        self.assertTrue(Product.objects.filter(pk=other_product.pk).exists())

    def test_cancellation_preserves_bids_notifies_distinct_bidders_once_and_blocks_future_bids(self):
        first = Bid.objects.create(auction=self.auction, buyer=self.bidder, amount=Decimal('110.00'))
        Bid.objects.create(auction=self.auction, buyer=self.bidder, amount=Decimal('120.00'))
        Bid.objects.create(auction=self.auction, buyer=self.second_bidder, amount=Decimal('130.00'))
        confirm = self.client.get(reverse('cancel_auction', args=[self.auction.pk]))
        self.assertContains(confirm, 'bidders will receive a cancellation notification')

        response = self.client.post(reverse('cancel_auction', args=[self.auction.pk]))
        self.assertRedirects(response, reverse('seller_auctions'))
        self.auction.refresh_from_db()
        self.assertEqual(self.auction.status, 'CANCELLED')
        self.assertEqual(Bid.objects.filter(auction=self.auction).count(), 3)
        self.assertEqual(Notification.objects.filter(user=self.bidder, notification_type='AUCTION_CANCELLED').count(), 1)
        self.assertEqual(Notification.objects.filter(user=self.second_bidder, notification_type='AUCTION_CANCELLED').count(), 1)

        self.client.post(reverse('cancel_auction', args=[self.auction.pk]))
        self.assertEqual(Notification.objects.filter(notification_type='AUCTION_CANCELLED').count(), 2)
        self.client.post(reverse('place_bid', args=[self.auction.pk]), {'amount': '150.00'})
        self.assertEqual(Bid.objects.filter(auction=self.auction).count(), 3)
        self.assertTrue(Bid.objects.filter(pk=first.pk).exists())

    def test_other_seller_cannot_cancel_and_completed_auction_cannot_be_cancelled(self):
        self.client.force_login(self.other_seller)
        self.assertEqual(self.client.post(reverse('cancel_auction', args=[self.auction.pk])).status_code, 404)
        self.client.force_login(self.seller)
        self.auction.status = 'COMPLETED'
        self.auction.save(update_fields=['status'])
        response = self.client.post(reverse('cancel_auction', args=[self.auction.pk]))
        self.assertRedirects(response, reverse('seller_auctions'))
        self.auction.refresh_from_db()
        self.assertEqual(self.auction.status, 'COMPLETED')

    def test_schedule_refresh_keeps_cancelled_auction_cancelled(self):
        self.auction.status = 'CANCELLED'
        self.auction.end_time = timezone.now() - timedelta(hours=1)
        self.auction.save(update_fields=['status', 'end_time'])
        call_command('refresh_auctions')
        self.auction.refresh_from_db()
        self.assertEqual(self.auction.status, 'CANCELLED')

    def test_analytics_uses_only_seller_data_and_labels_winning_value(self):
        own_ended = self.make_auction(self.seller, 'Own ended', status='CLOSED', ended=True, price='30.00')
        Bid.objects.create(auction=own_ended, buyer=self.bidder, amount=Decimal('75.00'))
        foreign = self.make_auction(self.other_seller, 'Foreign active', price='200.00')
        Bid.objects.create(auction=foreign, buyer=self.second_bidder, amount=Decimal('225.00'))

        response = self.client.get(reverse('seller_analytics'))
        self.assertEqual(response.context['total_products'], 2)
        self.assertEqual(response.context['closed_auctions'], 1)
        self.assertEqual(response.context['total_bids'], 1)
        self.assertEqual(response.context['winning_bid_value'], Decimal('75.00'))
        self.assertContains(response, 'Winning Bid Value')
        self.assertContains(response, 'not revenue received')

    def test_analytics_empty_state(self):
        self.auction.delete()
        self.product.delete()
        response = self.client.get(reverse('seller_analytics'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['total_products'], 0)
        self.assertEqual(response.context['active_auctions'], 0)
        self.assertEqual(response.context['total_bids'], 0)
        self.assertEqual(response.context['winning_bid_value'], 0)

    def test_seller_mode_navigation_links_phase_three_destinations(self):
        self.client.get(reverse('switch_mode', args=['SELLER']))
        response = self.client.get(reverse('dashboard'))
        for url_name in ('received_bids', 'seller_winners', 'seller_analytics'):
            self.assertContains(response, reverse(url_name))


class AuctionScheduleCommandTests(TestCase):
    def test_command_closes_ended_auction_and_notifies_winner(self):
        seller = User.objects.create_user('schedule-seller')
        winner = User.objects.create_user('schedule-winner')
        product = Product.objects.create(
            seller=seller,
            name='Ended Item',
            category='Home',
            description='Description',
            condition='GOOD',
            starting_price=Decimal('80.00'),
        )
        auction = Auction.objects.create(
            product=product,
            start_time=timezone.now() - timedelta(hours=2),
            end_time=timezone.now() - timedelta(hours=1),
            starting_bid=Decimal('80.00'),
            current_highest_bid=Decimal('100.00'),
            status='ACTIVE',
        )
        Bid.objects.create(auction=auction, buyer=winner, amount=Decimal('100.00'))

        call_command('refresh_auctions')

        auction.refresh_from_db()
        self.assertEqual(auction.status, 'CLOSED')
        self.assertEqual(auction.highest_bidder, winner)
        self.assertTrue(Notification.objects.filter(
            user=winner,
            notification_type='WINNER',
        ).exists())


class PhaseFourPasswordTests(TestCase):
    @override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
    def test_password_reset_email_token_completes_reset(self):
        user = User.objects.create_user('reset-user', email='reset@example.test', password='Initial!Password-948')
        response = self.client.post(reverse('password_reset'), {'email': user.email})
        self.assertRedirects(response, reverse('password_reset_done'))
        self.assertEqual(len(mail.outbox), 1)
        reset_url = next(line.strip() for line in mail.outbox[0].body.splitlines() if '/password-reset/' in line and 'http' in line)
        path = __import__('urllib.parse', fromlist=['urlsplit']).urlsplit(reset_url).path
        response = self.client.get(path, follow=True)
        self.assertEqual(response.status_code, 200)
        reset_confirm_path = response.request['PATH_INFO']
        response = self.client.post(reset_confirm_path, {
            'new_password1': 'Cobalt!Wren-94-Harbor',
            'new_password2': 'Cobalt!Wren-94-Harbor',
        })
        self.assertRedirects(response, reverse('password_reset_complete'))
        user.refresh_from_db()
        self.assertTrue(user.check_password('Cobalt!Wren-94-Harbor'))

    def test_password_change_requires_login_and_validates_password(self):
        url = reverse('password_change')
        self.assertRedirects(self.client.get(url), f'{reverse("login")}?next={url}')
        user = User.objects.create_user('change-user', password='Initial!Password-948')
        self.client.force_login(user)
        response = self.client.post(url, {
            'old_password': 'Initial!Password-948',
            'new_password1': 'Cobalt!Wren-94-Harbor',
            'new_password2': 'Cobalt!Wren-94-Harbor',
        })
        self.assertRedirects(response, reverse('password_change_done'))
        user.refresh_from_db()
        self.assertTrue(user.check_password('Cobalt!Wren-94-Harbor'))

    @override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
    def test_reset_request_response_does_not_reveal_unknown_email(self):
        response = self.client.post(reverse('password_reset'), {'email': 'missing@example.test'})
        self.assertRedirects(response, reverse('password_reset_done'))
        self.assertEqual(len(mail.outbox), 0)


class PhaseFourNotificationTests(TestCase):
    def test_notifications_are_paginated_and_private(self):
        user = User.objects.create_user('page-reader')
        other = User.objects.create_user('private-reader')
        for i in range(25):
            Notification.objects.create(user=user, title=f'Notice {i}', message='Visible', notification_type='BID')
        Notification.objects.create(user=other, title='Private notice', message='Secret', notification_type='BID')
        self.client.force_login(user)
        first = self.client.get(reverse('notifications'))
        self.assertEqual(first.context['notifications'].paginator.count, 25)
        self.assertEqual(len(first.context['notifications']), 20)
        second = self.client.get(reverse('notifications'), {'page': 2})
        self.assertEqual(len(second.context['notifications']), 5)
        self.assertNotContains(first, 'Private notice')


class PhaseFourGeneralFeatureTests(TestCase):
    def setUp(self):
        self.seller = User.objects.create_user('phase4-seller', email='seller@example.test')
        self.buyer = User.objects.create_user('phase4-buyer', email='buyer@example.test')
        self.other = User.objects.create_user('phase4-other')
        self.product = Product.objects.create(
            seller=self.seller, name='Reportable clock', category='Home',
            description='An auction listing', condition='GOOD', starting_price=Decimal('20.00'),
        )
        self.auction = Auction.objects.create(
            product=self.product, start_time=timezone.now() - timedelta(minutes=10),
            end_time=timezone.now() + timedelta(hours=3), starting_bid=Decimal('20.00'),
            current_highest_bid=Decimal('20.00'), status='ACTIVE',
        )
        self.client.force_login(self.buyer)

    def test_help_and_policy_pages_are_searchable_and_accessible(self):
        help_page = self.client.get(reverse('help_faq'), {'q': 'watchlist'})
        self.assertContains(help_page, 'How do I save an auction?')
        self.assertNotContains(help_page, 'How do bids work?')
        for name in ('terms', 'privacy', 'auction_rules'):
            self.assertEqual(self.client.get(reverse(name)).status_code, 200)
        self.assertContains(self.client.get(reverse('terms')), 'Draft policy')

    def test_buyer_can_report_once_and_staff_can_review(self):
        url = reverse('report_auction', args=[self.auction.pk])
        response = self.client.post(url, {'reason': 'SUSPICIOUS', 'description': 'Details here'})
        self.assertRedirects(response, reverse('auction_detail', args=[self.auction.pk]))
        self.assertEqual(AuctionReport.objects.filter(auction=self.auction, reporter=self.buyer).count(), 1)
        self.client.post(url, {'reason': 'FRAUD', 'description': 'duplicate'})
        self.assertEqual(AuctionReport.objects.count(), 1)
        staff = User.objects.create_superuser('phase4-admin', 'admin@example.test', 'Admin!Pass-948')
        self.client.force_login(staff)
        admin_url = reverse('admin:auction_auctionreport_changelist')
        self.assertEqual(self.client.get(admin_url).status_code, 200)

    def test_report_requires_login_and_valid_reason_and_existing_auction(self):
        url = reverse('report_auction', args=[self.auction.pk])
        self.client.logout()
        self.assertRedirects(self.client.post(url, {'reason': 'BAD'}), f'{reverse("login")}?next={url}')
        self.client.force_login(self.buyer)
        invalid = self.client.post(url, {'reason': 'BAD', 'description': 'x' * 1501})
        self.assertEqual(invalid.status_code, 200)
        self.assertEqual(AuctionReport.objects.count(), 0)
        missing = self.client.get(reverse('report_auction', args=[999999]))
        self.assertEqual(missing.status_code, 404)

    def test_seller_and_unauthorized_user_cannot_report_own_listing(self):
        self.client.force_login(self.seller)
        own_product = Product.objects.create(
            seller=self.seller, name='Seller own listing', category='Home',
            description='Own', condition='GOOD', starting_price=Decimal('10.00'),
        )
        own_auction = Auction.objects.create(
            product=own_product, start_time=timezone.now() - timedelta(minutes=5),
            end_time=timezone.now() + timedelta(hours=1), starting_bid=Decimal('10.00'), status='ACTIVE',
        )
        response = self.client.get(reverse('report_auction', args=[own_auction.pk]))
        self.assertEqual(response.status_code, 403)

    def test_recent_views_are_deduplicated_limited_and_private(self):
        detail_url = reverse('auction_detail', args=[self.auction.pk])
        self.client.get(detail_url)
        first = RecentlyViewedAuction.objects.get(user=self.buyer, auction=self.auction)
        first_time = first.last_viewed
        self.client.get(detail_url)
        self.assertEqual(RecentlyViewedAuction.objects.filter(user=self.buyer, auction=self.auction).count(), 1)
        first.refresh_from_db()
        self.assertGreaterEqual(first.last_viewed, first_time)
        self.assertEqual(self.client.get(reverse('recently_viewed')).status_code, 200)
        self.client.force_login(self.other)
        self.assertNotContains(self.client.get(reverse('recently_viewed')), self.product.name)

    def test_recent_views_keep_only_twenty_most_recent_records(self):
        for index in range(21):
            product = Product.objects.create(
                seller=self.seller, name=f'Recent {index}', category='Home',
                description='Recent test item', condition='GOOD', starting_price=Decimal('10.00'),
            )
            auction = Auction.objects.create(
                product=product, start_time=timezone.now() - timedelta(minutes=5),
                end_time=timezone.now() + timedelta(hours=2), starting_bid=Decimal('10.00'), status='ACTIVE',
            )
            RecentlyViewedAuction.objects.create(user=self.buyer, auction=auction)
        self.client.get(reverse('auction_detail', args=[self.auction.pk]))
        self.assertEqual(RecentlyViewedAuction.objects.filter(user=self.buyer).count(), 20)

    @override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
    def test_bid_events_email_seller_and_email_failure_does_not_break_bid(self):
        from unittest.mock import patch
        from django.core import mail
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(reverse('place_bid', args=[self.auction.pk]), {'amount': '25.00'})
        self.assertTrue(mail.outbox)
        self.assertEqual(mail.outbox[0].to, [self.seller.email])
        self.auction.refresh_from_db()
        self.auction.current_highest_bid = Decimal('25.00')
        self.auction.highest_bidder = self.buyer
        self.auction.save(update_fields=['current_highest_bid', 'highest_bidder'])
        with patch('auction.notifications.send_mail', side_effect=RuntimeError('mail unavailable')):
            self.client.force_login(self.other)
            with self.captureOnCommitCallbacks(execute=True):
                response = self.client.post(reverse('place_bid', args=[self.auction.pk]), {'amount': '30.00'})
        self.assertEqual(response.status_code, 302)
        self.assertTrue(Bid.objects.filter(auction=self.auction, amount=Decimal('30.00')).exists())

    @override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
    def test_duplicate_event_key_does_not_duplicate_notice_or_email(self):
        from auction.notifications import notify_user
        with self.captureOnCommitCallbacks(execute=True):
            first, created_first = notify_user(
                self.buyer, title='One event', message='Details', notification_type='BID', event_key='dedupe-test',
            )
            second, created_second = notify_user(
                self.buyer, title='One event', message='Details', notification_type='BID', event_key='dedupe-test',
            )
        self.assertTrue(created_first)
        self.assertFalse(created_second)
        self.assertEqual(first.pk, second.pk)
        self.assertEqual(Notification.objects.filter(user=self.buyer, event_key='dedupe-test').count(), 1)
        self.assertEqual(len(mail.outbox), 1)


class PhaseFiveAdminModuleTests(TestCase):
    def setUp(self):
        self.staff = User.objects.create_user('console-staff', email='staff@example.test', password='test-password-123', is_staff=True)
        self.superuser = User.objects.create_superuser('console-root', 'root@example.test', 'Strong!Admin-948')
        self.buyer = User.objects.create_user('console-buyer', email='buyer@example.test', password='test-password-123')
        self.seller = User.objects.create_user('console-seller', email='seller@example.test', password='test-password-123')
        self.seller.profile.role = 'SELLER'
        self.seller.profile.save(update_fields=['role'])
        self.product = Product.objects.create(
            seller=self.seller, name='Admin desk lamp', category='Home', description='Lamp listing',
            condition='GOOD', starting_price=Decimal('15.00'),
        )
        self.auction = Auction.objects.create(
            product=self.product, start_time=timezone.now() - timedelta(minutes=5),
            end_time=timezone.now() + timedelta(hours=3), starting_bid=Decimal('15.00'),
            current_highest_bid=Decimal('15.00'), status='ACTIVE',
        )
        self.report = AuctionReport.objects.create(
            auction=self.auction, reporter=self.buyer, reason='SUSPICIOUS', description='Please check details.',
        )
        self.client.force_login(self.staff)

    def test_admin_dashboard_is_staff_protected_and_uses_real_counts(self):
        response = self.client.get(reverse('staff_admin_dashboard'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['total_users'], User.objects.count())
        self.assertEqual(response.context['total_products'], 1)
        self.assertEqual(response.context['total_auctions'], 1)
        self.assertEqual(response.context['pending_reports'], 1)
        self.client.force_login(self.buyer)
        self.assertEqual(self.client.get(reverse('staff_admin_dashboard')).status_code, 403)

    def test_user_search_filter_and_account_status_actions(self):
        User.objects.create_user('search-match', email='needle@example.test')
        inactive = User.objects.create_user('inactive-match', email='inactive@example.test', is_active=False)
        searched = self.client.get(reverse('staff_admin_user_list'), {'q': 'needle'})
        self.assertEqual(searched.context['users'].paginator.count, 1)
        filtered = self.client.get(reverse('staff_admin_user_list'), {'active': 'inactive'})
        self.assertContains(filtered, 'inactive-match')
        self.assertNotIn(self.staff, filtered.context['users'])

        self.client.post(reverse('staff_admin_set_user_active', args=[self.staff.pk]), {'action': 'deactivate'})
        self.staff.refresh_from_db()
        self.assertTrue(self.staff.is_active)
        self.client.post(reverse('staff_admin_set_user_active', args=[self.superuser.pk]), {'action': 'deactivate'})
        self.superuser.refresh_from_db()
        self.assertTrue(self.superuser.is_active)
        self.client.post(reverse('staff_admin_set_user_active', args=[inactive.pk]), {'action': 'activate'})
        inactive.refresh_from_db()
        self.assertTrue(inactive.is_active)
        self.client.post(reverse('staff_admin_set_user_active', args=[inactive.pk]), {'action': 'deactivate'})
        inactive.refresh_from_db()
        self.assertFalse(inactive.is_active)

    def test_user_status_mutations_require_post(self):
        response = self.client.get(reverse('staff_admin_set_user_active', args=[self.buyer.pk]))
        self.assertEqual(response.status_code, 302)
        self.buyer.refresh_from_db()
        self.assertTrue(self.buyer.is_active)

        csrf_client = self.client_class(enforce_csrf_checks=True)
        csrf_client.force_login(self.staff)
        denied = csrf_client.post(reverse('staff_admin_set_user_active', args=[self.buyer.pk]), {'action': 'deactivate'})
        self.assertEqual(denied.status_code, 403)
        self.buyer.refresh_from_db()
        self.assertTrue(self.buyer.is_active)

    def test_product_filters_and_archive_restore_preserve_auction_history(self):
        response = self.client.get(reverse('staff_admin_product_list'), {'q': 'desk', 'seller': self.seller.pk, 'archived': 'no'})
        self.assertEqual(response.context['products'].paginator.count, 1)
        detail = reverse('staff_admin_product_detail', args=[self.product.pk])
        self.client.post(reverse('staff_admin_toggle_product_archive', args=[self.product.pk]))
        self.product.refresh_from_db()
        self.assertTrue(self.product.is_archived)
        self.assertTrue(Auction.objects.filter(pk=self.auction.pk, product=self.product).exists())
        self.client.post(reverse('staff_admin_toggle_product_archive', args=[self.product.pk]))
        self.product.refresh_from_db()
        self.assertFalse(self.product.is_archived)
        self.assertEqual(self.client.get(detail).status_code, 200)
        self.client.force_login(self.buyer)
        self.assertEqual(self.client.post(reverse('staff_admin_toggle_product_archive', args=[self.product.pk])).status_code, 403)

    def test_auction_search_filter_and_safe_cancellation_preserve_bids(self):
        Bid.objects.create(auction=self.auction, buyer=self.buyer, amount=Decimal('20.00'))
        response = self.client.get(reverse('staff_admin_auction_list'), {'q': 'desk', 'status': 'ACTIVE', 'seller': self.seller.pk})
        self.assertEqual(response.context['auctions'].paginator.count, 1)
        detail_url = reverse('staff_admin_auction_detail', args=[self.auction.pk])
        self.assertContains(self.client.get(detail_url), 'Bid history')
        cancel_url = reverse('staff_admin_cancel_auction', args=[self.auction.pk])
        confirm = self.client.get(cancel_url)
        self.assertEqual(confirm.status_code, 200)
        self.auction.refresh_from_db()
        self.assertEqual(self.auction.status, 'ACTIVE')
        self.client.post(cancel_url)
        self.auction.refresh_from_db()
        self.assertEqual(self.auction.status, 'CANCELLED')
        self.assertEqual(Bid.objects.filter(auction=self.auction).count(), 1)
        self.assertTrue(Notification.objects.filter(user=self.buyer, notification_type='AUCTION_CANCELLED').exists())
        self.client.post(cancel_url)
        self.assertEqual(Notification.objects.filter(user=self.buyer, notification_type='AUCTION_CANCELLED').count(), 1)

    def test_completed_or_cancelled_auctions_cannot_be_reopened_by_admin_action(self):
        for status in ('CANCELLED', 'COMPLETED'):
            with self.subTest(status=status):
                self.auction.status = status
                self.auction.save(update_fields=['status'])
                response = self.client.post(reverse('staff_admin_cancel_auction', args=[self.auction.pk]))
                self.assertRedirects(response, reverse('staff_admin_auction_detail', args=[self.auction.pk]))
                self.auction.refresh_from_db()
                self.assertEqual(self.auction.status, status)

    def test_report_review_permissions_and_admin_note(self):
        page = self.client.get(reverse('staff_admin_report_list'), {'status': 'OPEN', 'q': 'desk'})
        self.assertEqual(page.context['reports'].paginator.count, 1)
        detail = reverse('staff_admin_report_detail', args=[self.report.pk])
        self.assertEqual(self.client.get(detail).status_code, 200)
        response = self.client.post(reverse('staff_admin_review_report', args=[self.report.pk]), {
            'action': 'reviewed', 'admin_note': 'Listing checked against product description.',
        })
        self.assertRedirects(response, detail)
        self.report.refresh_from_db()
        self.assertEqual(self.report.status, 'REVIEWED')
        self.assertTrue(self.report.reviewed_at)
        self.assertEqual(self.report.admin_note, 'Listing checked against product description.')
        self.client.force_login(self.buyer)
        self.assertEqual(self.client.get(reverse('staff_admin_report_list')).status_code, 403)
        self.assertEqual(self.client.post(reverse('staff_admin_review_report', args=[self.report.pk]), {'action': 'dismissed'}).status_code, 403)

    def test_platform_reports_use_real_database_aggregations(self):
        Bid.objects.create(auction=self.auction, buyer=self.buyer, amount=Decimal('20.00'))
        response = self.client.get(reverse('staff_admin_platform_reports'))
        self.assertEqual(response.context['registrations'], User.objects.count())
        self.assertEqual(response.context['products']['total'], 1)
        self.assertEqual(response.context['auctions'], 1)
        self.assertEqual(response.context['bids']['total'], 1)
        self.assertEqual(response.context['reports'], 1)
        self.assertEqual(response.status_code, 200)

    def test_platform_analytics_uses_database_aggregates_and_restricts_access(self):
        Bid.objects.create(auction=self.auction, buyer=self.buyer, amount=Decimal('20.00'))
        response = self.client.get(reverse('staff_admin_platform_analytics'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(sum(row['total'] for row in response.context['registrations_by_month']), User.objects.count())
        self.assertEqual(sum(row['total'] for row in response.context['products_by_category']), 1)
        self.assertEqual(sum(row['total'] for row in response.context['bids_by_day']), 1)
        self.client.force_login(self.buyer)
        self.assertEqual(self.client.get(reverse('staff_admin_platform_analytics')).status_code, 403)


@override_settings(RAZORPAY_KEY_ID='rzp_test_mock', RAZORPAY_KEY_SECRET='mock-secret', RAZORPAY_WEBHOOK_SECRET='webhook-secret', RAZORPAY_CURRENCY='INR', EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
class RazorpayPaymentTests(TestCase):
    def setUp(self):
        self.seller = User.objects.create_user('pay-seller', password='pass-test-123')
        self.winner = User.objects.create_user('pay-winner', password='pass-test-123')
        self.other = User.objects.create_user('pay-other', password='pass-test-123')
        now = timezone.now()
        self.product = Product.objects.create(seller=self.seller, name='Payment Camera', category='Electronics', description='Camera', condition='GOOD', starting_price=Decimal('10.00'))
        self.auction = Auction.objects.create(product=self.product, start_time=now - timedelta(days=2), end_time=now - timedelta(days=1), starting_bid=Decimal('10.00'), current_highest_bid=Decimal('123.45'), highest_bidder=self.winner, status='CLOSED')
        self.winning_bid = Bid.objects.create(auction=self.auction, buyer=self.winner, amount=Decimal('123.45'))
        Profile.objects.update_or_create(user=self.winner, defaults={'full_name': 'Winner', 'phone_number': '1234567'})

    def _payment_and_attempt(self, status='PENDING'):
        payment = Payment.objects.create(auction=self.auction, buyer=self.winner, amount=Decimal('123.45'), payment_method='RAZORPAY', payment_status=status, currency='INR')
        attempt = PaymentAttempt.objects.create(payment=payment, attempt_number=1, status='PENDING', razorpay_order_id='order_test_1')
        payment.razorpay_order_id = attempt.razorpay_order_id
        payment.save(update_fields=['razorpay_order_id'])
        return payment, attempt

    def _webhook(self, event_id, event_type, entity):
        body = json.dumps({'event': event_type, 'payload': {'payment': {'entity': entity}}}).encode()
        signature = hmac.new(b'webhook-secret', body, hashlib.sha256).hexdigest()
        return self.client.post(reverse('razorpay_webhook'), body, content_type='application/json', HTTP_X_RAZORPAY_SIGNATURE=signature, HTTP_X_RAZORPAY_EVENT_ID=event_id)

    def test_only_winner_can_initiate_and_amount_is_server_derived_in_paise(self):
        self.client.force_login(self.other)
        denied = self.client.post(reverse('initiate_payment', args=[self.auction.pk]))
        self.assertEqual(denied.status_code, 403)
        self.client.force_login(self.winner)
        mock_client = Mock()
        mock_client.order.create.return_value = {'id': 'order_test_1', 'amount': 12345, 'currency': 'INR'}
        with patch('auction.payment_views._client', return_value=mock_client):
            response = self.client.post(reverse('initiate_payment', args=[self.auction.pk]), data=json.dumps({'amount': 1, 'buyer_id': self.other.pk}), content_type='application/json')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['amount'], 12345)
        self.assertEqual(mock_client.order.create.call_args.kwargs['data']['amount'], 12345)
        self.assertEqual(Payment.objects.get(auction=self.auction).amount, Decimal('123.45'))
        self.assertEqual(PaymentAttempt.objects.filter(payment__auction=self.auction).count(), 1)

    def test_unauthenticated_nonwinner_cancelled_and_legacy_completed_are_rejected(self):
        self.assertEqual(self.client.post(reverse('initiate_payment', args=[self.auction.pk])).status_code, 302)
        self.client.force_login(self.other)
        self.assertEqual(self.client.post(reverse('initiate_payment', args=[self.auction.pk])).status_code, 403)
        self.client.force_login(self.winner)
        self.auction.status = 'CANCELLED'
        self.auction.save(update_fields=['status'])
        self.assertEqual(self.client.post(reverse('initiate_payment', args=[self.auction.pk])).status_code, 409)
        self.auction.status = 'CLOSED'
        self.auction.save(update_fields=['status'])
        Payment.objects.create(auction=self.auction, buyer=self.winner, amount=Decimal('123.45'), payment_method='UPI', payment_status='COMPLETED', transaction_reference='legacy-ref')
        self.assertEqual(self.client.post(reverse('initiate_payment', args=[self.auction.pk])).status_code, 409)

    def test_invalid_signature_and_mismatched_provider_order_do_not_mark_paid(self):
        payment, attempt = self._payment_and_attempt()
        self.client.force_login(self.winner)
        client = Mock()
        client.utility.verify_payment_signature.side_effect = ValueError('invalid')
        payload = {'razorpay_order_id': attempt.razorpay_order_id, 'razorpay_payment_id': 'pay_test', 'razorpay_signature': 'bad'}
        with patch('auction.payment_views._client', return_value=client):
            response = self.client.post(reverse('verify_checkout', args=[self.auction.pk]), json.dumps(payload), content_type='application/json')
        self.assertEqual(response.status_code, 400)
        self.assertNotEqual(Payment.objects.get(pk=payment.pk).payment_status, 'PAID')

        client = Mock()
        client.utility.verify_payment_signature.return_value = None
        client.payment.fetch.return_value = {'id': 'pay_test', 'order_id': 'different_order', 'amount': 12345, 'currency': 'INR', 'status': 'captured'}
        with patch('auction.payment_views._client', return_value=client):
            response = self.client.post(reverse('verify_checkout', args=[self.auction.pk]), json.dumps({**payload, 'razorpay_signature': 'valid'}), content_type='application/json')
        self.assertEqual(response.status_code, 400)
        self.assertNotEqual(Payment.objects.get(pk=payment.pk).payment_status, 'PAID')

    def test_authorized_is_not_paid_and_capture_is_idempotent(self):
        payment, attempt = self._payment_and_attempt()
        self.client.force_login(self.winner)
        payload = {'razorpay_order_id': attempt.razorpay_order_id, 'razorpay_payment_id': 'pay_test', 'razorpay_signature': 'valid'}
        client = Mock()
        client.utility.verify_payment_signature.return_value = None
        client.payment.fetch.return_value = {'id': 'pay_test', 'order_id': attempt.razorpay_order_id, 'amount': 12345, 'currency': 'INR', 'status': 'authorized'}
        with patch('auction.payment_views._client', return_value=client):
            response = self.client.post(reverse('verify_checkout', args=[self.auction.pk]), json.dumps(payload), content_type='application/json')
        self.assertEqual(response.status_code, 202)
        payment.refresh_from_db()
        self.assertNotEqual(payment.payment_status, 'PAID')
        client.payment.fetch.return_value['status'] = 'captured'
        with patch('auction.payment_views._client', return_value=client):
            first = self.client.post(reverse('verify_checkout', args=[self.auction.pk]), json.dumps(payload), content_type='application/json')
            second = self.client.post(reverse('verify_checkout', args=[self.auction.pk]), json.dumps(payload), content_type='application/json')
        self.assertEqual(first.json()['status'], 'PAID')
        self.assertEqual(second.json()['status'], 'PAID')
        payment.refresh_from_db()
        self.assertEqual(payment.payment_status, 'PAID')
        self.assertEqual(payment.razorpay_payment_id, 'pay_test')
        self.assertEqual(PaymentAttempt.objects.filter(payment=payment).count(), 1)

    def test_retry_after_failed_attempt_creates_new_attempt_but_same_obligation(self):
        payment, first_attempt = self._payment_and_attempt('FAILED')
        first_attempt.status = 'FAILED'
        first_attempt.save(update_fields=['status'])
        self.client.force_login(self.winner)
        client = Mock()
        with patch('auction.payment_views._client', return_value=client):
            response = self.client.post(reverse('initiate_payment', args=[self.auction.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(Payment.objects.filter(auction=self.auction).count(), 1)
        self.assertEqual(PaymentAttempt.objects.filter(payment=payment).count(), 2)
        self.assertEqual(response.json()['order_id'], 'order_test_1')
        self.assertEqual(client.order.create.call_count, 0)

    def test_repeated_initiation_reuses_existing_provider_order(self):
        self.client.force_login(self.winner)
        client = Mock()
        client.order.create.return_value = {'id': 'order_once', 'amount': 12345, 'currency': 'INR'}
        with patch('auction.payment_views._client', return_value=client):
            first = self.client.post(reverse('initiate_payment', args=[self.auction.pk]))
            second = self.client.post(reverse('initiate_payment', args=[self.auction.pk]))
        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(first.json()['order_id'], second.json()['order_id'])
        self.assertEqual(client.order.create.call_count, 1)
        self.assertEqual(Payment.objects.filter(auction=self.auction).count(), 1)
        self.assertEqual(PaymentAttempt.objects.filter(payment__auction=self.auction).count(), 1)

    def test_webhook_signature_deduplication_and_out_of_order_event(self):
        payment, attempt = self._payment_and_attempt()
        entity = {'entity': 'payment', 'id': 'pay_hook', 'order_id': attempt.razorpay_order_id, 'amount': 12345, 'currency': 'INR', 'status': 'captured'}
        self.assertEqual(self._webhook('evt-captured', 'payment.captured', entity).status_code, 200)
        self.assertEqual(self._webhook('evt-captured', 'payment.captured', entity).status_code, 200)
        self.assertEqual(PaymentWebhookEvent.objects.filter(event_id='evt-captured').count(), 1)
        failed_entity = {**entity, 'status': 'failed', 'error_code': 'TEMP_ERROR'}
        self.assertEqual(self._webhook('evt-failed-late', 'payment.failed', failed_entity).status_code, 200)
        payment.refresh_from_db()
        attempt.refresh_from_db()
        self.assertEqual(payment.payment_status, 'PAID')
        self.assertEqual(attempt.status, 'CAPTURED')

    def test_order_paid_without_payment_entity_does_not_fake_capture(self):
        payment, attempt = self._payment_and_attempt()
        body = json.dumps({'event': 'order.paid', 'payload': {'order': {'entity': {'entity': 'order', 'id': attempt.razorpay_order_id, 'status': 'paid'}}}}).encode()
        signature = hmac.new(b'webhook-secret', body, hashlib.sha256).hexdigest()
        response = self.client.post(reverse('razorpay_webhook'), body, content_type='application/json', HTTP_X_RAZORPAY_SIGNATURE=signature, HTTP_X_RAZORPAY_EVENT_ID='evt-order-only')
        payment.refresh_from_db()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(payment.payment_status, 'PENDING')
        self.assertEqual(PaymentWebhookEvent.objects.get(event_id='evt-order-only').status, 'PROCESSED')

    def test_invalid_webhook_signature_is_rejected_without_record(self):
        body = json.dumps({'event': 'payment.captured'}).encode()
        response = self.client.post(reverse('razorpay_webhook'), body, content_type='application/json', HTTP_X_RAZORPAY_SIGNATURE='wrong', HTTP_X_RAZORPAY_EVENT_ID='evt-invalid')
        self.assertEqual(response.status_code, 400)
        self.assertFalse(PaymentWebhookEvent.objects.filter(event_id='evt-invalid').exists())

    def test_payment_views_are_scoped_and_dashboard_shows_paid_status(self):
        payment, _attempt = self._payment_and_attempt('PAID')
        payment.razorpay_payment_id = 'pay_view'
        payment.paid_at = timezone.now()
        payment.save(update_fields=['razorpay_payment_id', 'paid_at'])
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(reverse('payment_detail', args=[self.auction.pk])).status_code, 403)
        payment_history = self.client.get(reverse('my_payments'))
        self.assertEqual(payment_history.status_code, 200)
        self.assertEqual(payment_history.context['payments'].count(), 0)
        self.client.force_login(self.winner)
        self.assertEqual(self.client.get(reverse('payment_detail', args=[self.auction.pk])).status_code, 200)
        dashboard = self.client.get(reverse('dashboard'))
        self.assertContains(dashboard, 'Paid')
