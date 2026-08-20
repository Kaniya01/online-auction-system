from django.contrib import admin
from .models import (
    Profile,
    Product,
    ProductImage,
    Auction,
    Bid,
    Payment,
    Notification,
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
    )


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