from django.contrib.auth.models import User
from django.db import models
from django.core.validators import MinValueValidator


class Profile(models.Model):
    ROLE_CHOICES = [
        ('BUYER', 'Buyer'),
        ('SELLER', 'Seller'),
        ('ADMIN', 'Administrator'),
    ]

    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name='profile'
    )
    full_name = models.CharField(max_length=150)
    phone_number = models.CharField(max_length=15)
    role = models.CharField(
        max_length=10,
        choices=ROLE_CHOICES,
        default='BUYER'
    )
    profile_picture = models.ImageField(
        upload_to='profile_pictures/',
        blank=True,
        null=True
    )

    def __str__(self):
        return self.user.username


class Product(models.Model):
    CONDITION_CHOICES = [
        ('NEW', 'New'),
        ('LIKE_NEW', 'Like New'),
        ('GOOD', 'Good'),
        ('FAIR', 'Fair'),
        ('USED', 'Used'),
    ]

    seller = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='products'
    )
    name = models.CharField(max_length=200)
    category = models.CharField(max_length=100)
    description = models.TextField()
    condition = models.CharField(
        max_length=20,
        choices=CONDITION_CHOICES
    )
    starting_price = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        validators=[MinValueValidator(0.01)]
    )
    is_archived = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name


class ProductImage(models.Model):
    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        related_name='images'
    )
    image = models.ImageField(upload_to='product_images/')
    uploaded_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Image for {self.product.name}"


class Auction(models.Model):
    STATUS_CHOICES = [
        ('SCHEDULED', 'Scheduled'),
        ('ACTIVE', 'Active'),
        ('CLOSED', 'Closed'),
        ('COMPLETED', 'Completed'),
        ('CANCELLED', 'Cancelled'),
    ]

    product = models.OneToOneField(
        Product,
        on_delete=models.PROTECT,
        related_name='auction'
    )
    start_time = models.DateTimeField()
    end_time = models.DateTimeField()
    starting_bid = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        validators=[MinValueValidator(0.01)]
    )
    current_highest_bid = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=0
    )
    highest_bidder = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='won_auctions'
    )
    status = models.CharField(
        max_length=15,
        choices=STATUS_CHOICES,
        default='SCHEDULED'
    )
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.product.name} Auction"


class Bid(models.Model):
    auction = models.ForeignKey(
        Auction,
        on_delete=models.CASCADE,
        related_name='bids'
    )
    buyer = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='bids'
    )
    amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        validators=[MinValueValidator(0.01)]
    )
    bid_time = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-bid_time']

    def __str__(self):
        return f"{self.buyer.username} - ₹{self.amount}"


class Watchlist(models.Model):
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='watchlist_items',
    )
    auction = models.ForeignKey(
        Auction,
        on_delete=models.CASCADE,
        related_name='watchlist_entries',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        constraints = [
            models.UniqueConstraint(
                fields=['user', 'auction'],
                name='unique_user_auction_watchlist',
            ),
        ]

    def __str__(self):
        return f"{self.user.username} watches {self.auction}"


class Payment(models.Model):
    PAYMENT_METHOD_CHOICES = [
        ('UPI', 'UPI'),
        ('CARD', 'Credit/Debit Card'),
        ('NET_BANKING', 'Net Banking'),
    ]

    PAYMENT_STATUS_CHOICES = [
        ('UNPAID', 'Unpaid'),
        ('PENDING', 'Pending'),
        ('FAILED', 'Failed'),
        ('PAID', 'Paid'),
        # Retained for legacy rows. These values are not proof of a
        # Razorpay-verified capture.
        ('COMPLETED', 'Completed'),
        ('CANCELLED', 'Cancelled'),
    ]

    auction = models.OneToOneField(
        Auction,
        on_delete=models.CASCADE,
        related_name='payment'
    )
    buyer = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='payments'
    )
    amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        validators=[MinValueValidator(0.01)]
    )
    payment_method = models.CharField(
        max_length=20,
        choices=PAYMENT_METHOD_CHOICES + [('RAZORPAY', 'Razorpay')],
        default='RAZORPAY',
    )
    payment_status = models.CharField(
        max_length=15,
        choices=PAYMENT_STATUS_CHOICES,
        default='UNPAID'
    )
    transaction_reference = models.CharField(
        max_length=50,
        unique=True,
        blank=True,
        null=True,
    )
    payment_date = models.DateTimeField(
        auto_now_add=True
    )
    razorpay_order_id = models.CharField(max_length=64, unique=True, null=True, blank=True)
    razorpay_payment_id = models.CharField(max_length=64, unique=True, null=True, blank=True)
    currency = models.CharField(max_length=3, default='INR')
    paid_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.transaction_reference or f"Payment for auction {self.auction_id}"


class PaymentAttempt(models.Model):
    STATUS_CHOICES = [
        ('CREATING', 'Creating order'),
        ('PENDING', 'Pending'),
        ('AUTHORIZED', 'Authorized, not captured'),
        ('FAILED', 'Failed'),
        ('CANCELLED', 'Cancelled'),
        ('CAPTURED', 'Captured'),
    ]
    payment = models.ForeignKey(Payment, on_delete=models.CASCADE, related_name='attempts')
    attempt_number = models.PositiveIntegerField()
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default='CREATING')
    razorpay_order_id = models.CharField(max_length=64, null=True, blank=True)
    razorpay_payment_id = models.CharField(max_length=64, unique=True, null=True, blank=True)
    failure_code = models.CharField(max_length=100, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-attempt_number']
        constraints = [models.UniqueConstraint(fields=['payment', 'attempt_number'], name='unique_payment_attempt_number')]

    def __str__(self):
        return f"{self.payment_id} attempt {self.attempt_number} ({self.status})"


class PaymentWebhookEvent(models.Model):
    STATUS_CHOICES = [('RECEIVED', 'Received'), ('PROCESSING', 'Processing'), ('PROCESSED', 'Processed'), ('FAILED', 'Failed')]
    event_id = models.CharField(max_length=128, unique=True)
    event_type = models.CharField(max_length=80)
    status = models.CharField(max_length=12, choices=STATUS_CHOICES, default='RECEIVED')
    attempt = models.ForeignKey(PaymentAttempt, on_delete=models.SET_NULL, null=True, blank=True, related_name='webhook_events')
    received_at = models.DateTimeField(auto_now_add=True)
    processed_at = models.DateTimeField(null=True, blank=True)
    error_message = models.CharField(max_length=240, blank=True)

    class Meta:
        ordering = ['-received_at']

    def __str__(self):
        return f"{self.event_type} ({self.event_id})"


class Notification(models.Model):
    NOTIFICATION_TYPE_CHOICES = [
        ('REGISTRATION', 'Registration'),
        ('BID', 'Bid'),
        ('OUTBID', 'Outbid'),
        ('AUCTION_CREATED', 'Auction Created'),
        ('AUCTION_ENDING', 'Auction Ending'),
        ('WINNER', 'Winner'),
        ('PAYMENT', 'Payment'),
        ('AUCTION_CANCELLED', 'Auction Cancelled'),
        ('AUCTION_CLOSED', 'Auction Closed'),
    ]

    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='notifications'
    )
    title = models.CharField(max_length=200)
    message = models.TextField()
    notification_type = models.CharField(
        max_length=20,
        choices=NOTIFICATION_TYPE_CHOICES
    )
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    event_key = models.CharField(max_length=120, blank=True)
    link_url = models.CharField(max_length=300, blank=True)

    def __str__(self):
        return f"{self.user.username} - {self.title}"

    class Meta:
        indexes = [models.Index(fields=['user', 'is_read', '-created_at'], name='notif_user_read_date_idx')]
        constraints = [
            models.UniqueConstraint(
                fields=['user', 'event_key'],
                condition=~models.Q(event_key=''),
                name='unique_notification_event_per_user',
            ),
        ]


class AuctionReport(models.Model):
    REASON_CHOICES = [
        ('MISLEADING', 'Misleading description'),
        ('SUSPICIOUS', 'Suspicious listing'),
        ('INAPPROPRIATE', 'Inappropriate content'),
        ('INCORRECT', 'Incorrect product information'),
        ('FRAUD', 'Suspected fraud'),
        ('OTHER', 'Other'),
    ]
    STATUS_CHOICES = [('OPEN', 'Open'), ('REVIEWED', 'Reviewed'), ('DISMISSED', 'Dismissed')]

    auction = models.ForeignKey(Auction, on_delete=models.PROTECT, related_name='reports')
    reporter = models.ForeignKey(User, on_delete=models.CASCADE, related_name='auction_reports')
    reason = models.CharField(max_length=20, choices=REASON_CHOICES)
    description = models.TextField(blank=True, max_length=1500)
    admin_note = models.TextField(blank=True, max_length=2000)
    status = models.CharField(max_length=12, choices=STATUS_CHOICES, default='OPEN')
    created_at = models.DateTimeField(auto_now_add=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']
        constraints = [models.UniqueConstraint(fields=['auction', 'reporter'], name='unique_reporter_auction')]
        indexes = [models.Index(fields=['status', '-created_at'], name='report_status_date_idx')]

    def __str__(self):
        return f'{self.get_reason_display()} report for {self.auction}'


class RecentlyViewedAuction(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='recently_viewed_auctions')
    auction = models.ForeignKey(Auction, on_delete=models.CASCADE, related_name='recently_viewed_by')
    last_viewed = models.DateTimeField(auto_now=True, db_index=True)

    class Meta:
        ordering = ['-last_viewed']
        constraints = [models.UniqueConstraint(fields=['user', 'auction'], name='unique_user_recent_auction')]
        indexes = [models.Index(fields=['user', '-last_viewed'], name='recent_user_viewed_idx')]

    def __str__(self):
        return f'{self.user.username} viewed {self.auction}'
