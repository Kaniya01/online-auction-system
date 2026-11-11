from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.models import User
from django.core.management import call_command
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .browse_views import update_auction_status
from .models import Auction, Bid, Notification, Product, Profile, Watchlist


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
