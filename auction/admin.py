from django.contrib import admin
from .models import (
    Profile,
    Product,
    ProductImage,
    Auction,
    Bid,
    Payment,
    PaymentAttempt,
    PaymentWebhookEvent,
    Notification,
    Watchlist,
    AuctionReport,
    RecentlyViewedAuction,
)


@admin.register(Profile)
class ProfileAdmin(admin.ModelAdmin):
    list_display = ('user', 'full_name', 'role', 'phone_number')
    list_filter = ('role',)
    search_fields = ('user__username', 'full_name', 'phone_number')


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = (
        'name',
        'seller',
        'category',
        'condition',
        'starting_price',
        'is_archived',
        'created_at',
    )
    list_filter = ('category', 'condition')
    search_fields = ('name', 'category', 'seller__username')


@admin.register(ProductImage)
class ProductImageAdmin(admin.ModelAdmin):
    list_display = ('product', 'uploaded_at')


@admin.register(Auction)
class AuctionAdmin(admin.ModelAdmin):
    list_display = (
        'product',
        'start_time',
        'end_time',
        'starting_bid',
        'current_highest_bid',
        'highest_bidder',
        'status',
    )
    list_filter = ('status',)
    search_fields = (
        'product__name',
        'highest_bidder__username',
    )


@admin.register(Bid)
class BidAdmin(admin.ModelAdmin):
    list_display = (
        'auction',
        'buyer',
        'amount',
        'bid_time',
    )
    list_filter = ('bid_time',)
    search_fields = (
        'buyer__username',
        'auction__product__name',
    )


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = (
        'auction',
        'buyer',
        'amount',
        'payment_method',
        'payment_status',
        'transaction_reference',
        'payment_date',
    )
    list_filter = ('payment_status', 'payment_method')
    search_fields = (
        'buyer__username',
        'transaction_reference',
        'razorpay_order_id',
        'razorpay_payment_id',
    )
    readonly_fields = tuple(field.name for field in Payment._meta.fields)

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(PaymentAttempt)
class PaymentAttemptAdmin(admin.ModelAdmin):
    list_display = ('payment', 'attempt_number', 'status', 'razorpay_order_id', 'razorpay_payment_id', 'created_at')
    list_filter = ('status',)
    search_fields = ('razorpay_order_id', 'razorpay_payment_id', 'payment__buyer__username')
    readonly_fields = tuple(field.name for field in PaymentAttempt._meta.fields)

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(PaymentWebhookEvent)
class PaymentWebhookEventAdmin(admin.ModelAdmin):
    list_display = ('event_id', 'event_type', 'status', 'received_at', 'processed_at')
    list_filter = ('status', 'event_type')
    search_fields = ('event_id', 'event_type')
    readonly_fields = tuple(field.name for field in PaymentWebhookEvent._meta.fields)

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = (
        'user',
        'title',
        'notification_type',
        'is_read',
        'created_at',
    )
    list_filter = ('notification_type', 'is_read')
    search_fields = ('user__username', 'title', 'message')
    readonly_fields = ('created_at',)


@admin.register(Watchlist)
class WatchlistAdmin(admin.ModelAdmin):
    list_display = ('user', 'auction', 'created_at')
    search_fields = ('user__username', 'auction__product__name')
    list_select_related = ('user', 'auction', 'auction__product')


@admin.register(AuctionReport)
class AuctionReportAdmin(admin.ModelAdmin):
    list_display = ('auction', 'reporter', 'reason', 'status', 'created_at', 'reviewed_at')
    list_filter = ('status', 'reason', 'created_at')
    search_fields = ('auction__product__name', 'reporter__username', 'description', 'admin_note')
    list_select_related = ('auction__product', 'reporter')
    readonly_fields = ('auction', 'reporter', 'reason', 'description', 'created_at')
    actions = ('mark_reviewed', 'dismiss_reports')

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def save_model(self, request, obj, form, change):
        if obj.status != 'OPEN' and (obj.reviewed_at is None or 'status' in form.changed_data):
            from django.utils import timezone
            obj.reviewed_at = timezone.now()
        super().save_model(request, obj, form, change)

    @admin.action(description='Mark selected reports as reviewed')
    def mark_reviewed(self, request, queryset):
        from django.utils import timezone
        queryset.update(status='REVIEWED', reviewed_at=timezone.now())

    @admin.action(description='Dismiss selected reports')
    def dismiss_reports(self, request, queryset):
        from django.utils import timezone
        queryset.update(status='DISMISSED', reviewed_at=timezone.now())


@admin.register(RecentlyViewedAuction)
class RecentlyViewedAuctionAdmin(admin.ModelAdmin):
    list_display = ('user', 'auction', 'last_viewed')
    list_select_related = ('user', 'auction', 'auction__product')
