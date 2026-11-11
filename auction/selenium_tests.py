"""End-to-end Chrome workflows; run explicitly with auction.selenium_tests."""

import os
from pathlib import Path
import sys
from datetime import timedelta
from decimal import Decimal
from unittest import SkipTest

from django.contrib.auth.models import User
from django.test import LiveServerTestCase
from django.urls import reverse
from django.utils import timezone
from selenium import webdriver
from selenium.common.exceptions import WebDriverException
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from .models import Auction, Bid, Product, Profile


class AuctionHubBrowserTests(LiveServerTestCase):
    """Demonstrate core visitor, buyer, seller, schedule, and payment pages."""

    wait_seconds = 10

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        options = webdriver.ChromeOptions()
        options.page_load_strategy = 'eager'
        options.add_argument('--window-size=1440,1000')
        if os.getenv('SELENIUM_HEADLESS', '1').strip().lower() not in ('0', 'false', 'no'):
            options.add_argument('--headless=new')

        try:
            # Selenium Manager discovers/downloads a matching driver as needed.
            cls.browser = webdriver.Chrome(options=options)
        except WebDriverException as exc:
            super().tearDownClass()
            raise SkipTest(f'Chrome WebDriver could not start: {type(exc).__name__}') from exc

    @classmethod
    def tearDownClass(cls):
        browser = getattr(cls, 'browser', None)
        if browser is not None:
            browser.quit()
        super().tearDownClass()

    def setUp(self):
        super().setUp()
        self.driver = self.browser
        self.wait = WebDriverWait(self.driver, self.wait_seconds)
        self.driver.delete_all_cookies()
        self._create_test_data()

    def tearDown(self):
        # Browser is owned by the class and is also closed in tearDownClass,
        # including when an individual browser test raises an assertion.
        self.driver.delete_all_cookies()
        super().tearDown()

    def _callTestMethod(self, method):
        try:
            return super()._callTestMethod(method)
        except Exception:
            self._save_failure_screenshot()
            raise

    def _save_failure_screenshot(self):
        browser = getattr(self, 'driver', None)
        if browser is None:
            return
        artifact_dir = Path(__file__).resolve().parents[1] / 'test-artifacts' / 'selenium'
        artifact_dir.mkdir(parents=True, exist_ok=True)
        screenshot_path = artifact_dir / f'{self.id().split(".")[-1]}.png'
        try:
            browser.save_screenshot(str(screenshot_path))
            sys.stderr.write(f'Browser failure screenshot: {screenshot_path}\n')
        except WebDriverException:
            pass

    def _create_user(self, username):
        user = User.objects.create_user(username=username, password='TestPass!2026')
        Profile.objects.update_or_create(
            user=user,
            defaults={'full_name': username.title(), 'phone_number': '5551234567'},
        )
        return user

    def _create_auction(self, seller, title, start, end, status):
        product = Product.objects.create(
            seller=seller,
            name=title,
            category='Electronics',
            description=f'Test listing for {title}',
            condition='GOOD',
            starting_price=Decimal('10.00'),
        )
        return Auction.objects.create(
            product=product,
            start_time=start,
            end_time=end,
            starting_bid=Decimal('10.00'),
            current_highest_bid=Decimal('10.00'),
            status=status,
        )

    def _create_test_data(self):
        now = timezone.now()
        self.buyer = self._create_user('browser-buyer')
        self.seller = self._create_user('browser-seller')
        self.active_auction = self._create_auction(
            self.seller, 'Browser Active Auction', now - timedelta(hours=1),
            now + timedelta(days=1), 'ACTIVE',
        )
        self.scheduled_auction = self._create_auction(
            self.seller, 'Browser Scheduled Auction', now + timedelta(days=1),
            now + timedelta(days=2), 'SCHEDULED',
        )
        self.won_auction = self._create_auction(
            self.seller, 'Browser Won Auction', now - timedelta(days=2),
            now - timedelta(days=1), 'COMPLETED',
        )
        winning_bid = Bid.objects.create(
            auction=self.won_auction,
            buyer=self.buyer,
            amount=Decimal('15.50'),
        )
        self.won_auction.highest_bidder = winning_bid.buyer
        self.won_auction.current_highest_bid = winning_bid.amount
        self.won_auction.save(update_fields=['highest_bidder', 'current_highest_bid'])

    def _open(self, route_name, *args):
        self.driver.get(f'{self.live_server_url}{reverse(route_name, args=args)}')

    def _login(self, username):
        self._open('login')
        self.wait.until(EC.visibility_of_element_located((By.ID, 'loginForm')))
        self.driver.find_element(By.NAME, 'username').send_keys(username)
        self.driver.find_element(By.NAME, 'password').send_keys('TestPass!2026')
        self.driver.find_element(By.CSS_SELECTOR, '#loginForm button[type="submit"]').click()
        self.wait.until(EC.url_contains('/dashboard/'))

    def _switch_to_seller(self):
        self._open('switch_mode', 'SELLER')
        self.wait.until(EC.url_contains('/dashboard/'))

    def _click_link(self, route_name, *args):
        href = reverse(route_name, args=args)
        link = self.wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, f'a[href="{href}"]')))
        link.click()

    def test_login_page_and_valid_login(self):
        self._open('login')
        heading = self.wait.until(EC.visibility_of_element_located((By.TAG_NAME, 'h1')))
        self.assertEqual(heading.text, 'Welcome Back')

        self.driver.find_element(By.NAME, 'username').send_keys(self.buyer.username)
        self.driver.find_element(By.NAME, 'password').send_keys('TestPass!2026')
        self.driver.find_element(By.CSS_SELECTOR, '#loginForm button[type="submit"]').click()
        self.wait.until(EC.url_contains('/dashboard/'))
        self.assertTrue(self.driver.find_element(By.CLASS_NAME, 'welcome-banner').is_displayed())

    def test_invalid_login_shows_error(self):
        self._open('login')
        self.wait.until(EC.visibility_of_element_located((By.ID, 'loginForm')))
        self.driver.find_element(By.NAME, 'username').send_keys(self.buyer.username)
        self.driver.find_element(By.NAME, 'password').send_keys('incorrect-password')
        self.driver.find_element(By.CSS_SELECTOR, '#loginForm button[type="submit"]').click()
        self.wait.until(EC.visibility_of_element_located((
            By.XPATH, "//*[contains(normalize-space(.), 'Invalid username or password.')]"
        )))
        self.assertIn('/login/', self.driver.current_url)

    def test_buyer_dashboard_browse_and_auction_details(self):
        self._login(self.buyer.username)
        self.assertTrue(self.driver.find_element(By.CLASS_NAME, 'welcome-banner').is_displayed())
        self._click_link('browse_auctions')
        self.wait.until(EC.url_contains('/browse-auctions/'))
        self.assertIn('Browse Auctions', self.driver.page_source)

        self._open('auction_detail', self.active_auction.pk)
        product_heading = self.wait.until(EC.visibility_of_element_located((By.TAG_NAME, 'h1')))
        self.assertIn(self.active_auction.product.name, product_heading.text)
        self.assertIn('Current', self.driver.page_source)

    def test_seller_dashboard_products_creation_and_auction_management(self):
        self._login(self.seller.username)
        self._switch_to_seller()
        self.assertTrue(self.driver.find_element(By.CLASS_NAME, 'welcome-banner').is_displayed())

        self._click_link('seller_products')
        self.wait.until(EC.visibility_of_element_located((
            By.XPATH, "//h1[normalize-space()='My Products']"
        )))
        self._click_link('add_product')
        self.wait.until(EC.visibility_of_element_located((
            By.XPATH, "//h1[normalize-space()='Add Product']"
        )))

        self._click_link('seller_auctions')
        self.wait.until(EC.visibility_of_element_located((
            By.XPATH, "//h1[normalize-space()='My Auctions']"
        )))

    def test_seller_can_open_eligible_schedule_edit_form(self):
        self._login(self.seller.username)
        self._switch_to_seller()
        self._click_link('seller_auctions')
        self.wait.until(EC.visibility_of_element_located((
            By.XPATH, "//h1[normalize-space()='My Auctions']"
        )))
        self._click_link('edit_auction', self.scheduled_auction.pk)
        self.wait.until(EC.visibility_of_element_located((By.NAME, 'start_time')))
        self.assertTrue(self.driver.find_element(By.NAME, 'end_time').is_displayed())

    def test_winning_buyer_payment_page_loads_without_checkout(self):
        self._login(self.buyer.username)
        self._open('payment_detail', self.won_auction.pk)
        self.wait.until(EC.visibility_of_element_located((
            By.XPATH, "//*[contains(normalize-space(.), 'Winning auction payment')]"
        )))
        self.assertIn(self.won_auction.product.name, self.driver.page_source)
        self.assertIn('15.50', self.driver.page_source)
        # This test only renders the eligible buyer's page; it never submits
        # Pay Now or calls Razorpay's order/payment endpoints.
