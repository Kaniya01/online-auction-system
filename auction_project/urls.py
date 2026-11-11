from django.contrib import admin
from django.urls import path
from django.contrib.auth import views as auth_views
from django.conf import settings
from django.conf.urls.static import static

from auction import views
from auction import browse_views
from auction import admin_views
from auction import payment_views


urlpatterns = [

    # =====================================================
    # ADMIN
    # =====================================================

    path('admin/', admin.site.urls),

    # =====================================================
    # HOME / DASHBOARD
    # =====================================================

    path('', views.dashboard, name='home'),
    path('dashboard/', views.dashboard, name='dashboard'),

    # =====================================================
    # AUTHENTICATION
    # =====================================================

    path('register/', views.register, name='register'),
    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),
    path('password-reset/', views.SafePasswordResetView.as_view(), name='password_reset'),
    path('password-reset/done/', auth_views.PasswordResetDoneView.as_view(template_name='registration/password_reset_done.html'), name='password_reset_done'),
    path('password-reset/<uidb64>/<token>/', auth_views.PasswordResetConfirmView.as_view(template_name='registration/password_reset_confirm.html', success_url='/password-reset/complete/'), name='password_reset_confirm'),
    path('password-reset/complete/', auth_views.PasswordResetCompleteView.as_view(template_name='registration/password_reset_complete.html'), name='password_reset_complete'),
    path('password-change/', views.SafePasswordChangeView.as_view(), name='password_change'),
    path('password-change/done/', auth_views.PasswordChangeDoneView.as_view(template_name='registration/password_change_done.html'), name='password_change_done'),
    path('help/', views.help_faq, name='help_faq'),
    path('terms/', views.terms_and_conditions, name='terms'),
    path('privacy/', views.privacy_policy, name='privacy'),
    path('auction-rules/', views.auction_rules, name='auction_rules'),
    path('my-payments/', payment_views.my_payments, name='my_payments'),
    path('payments/<int:auction_id>/', payment_views.payment_detail, name='payment_detail'),
    path('payments/<int:auction_id>/initiate/', payment_views.initiate_payment, name='initiate_payment'),
    path('payments/verify/<int:auction_id>/', payment_views.verify_checkout, name='verify_checkout'),
    path('payments/razorpay/webhook/', payment_views.razorpay_webhook, name='razorpay_webhook'),
    path('admin-console/', admin_views.dashboard, name='staff_admin_dashboard'),
    path('admin-console/users/', admin_views.user_list, name='staff_admin_user_list'),
    path('admin-console/users/<int:user_id>/', admin_views.user_detail, name='staff_admin_user_detail'),
    path('admin-console/users/<int:user_id>/status/', admin_views.set_user_active, name='staff_admin_set_user_active'),
    path('admin-console/products/', admin_views.product_list, name='staff_admin_product_list'),
    path('admin-console/products/<int:product_id>/', admin_views.product_detail, name='staff_admin_product_detail'),
    path('admin-console/products/<int:product_id>/archive/', admin_views.toggle_product_archive, name='staff_admin_toggle_product_archive'),
    path('admin-console/auctions/', admin_views.auction_list, name='staff_admin_auction_list'),
    path('admin-console/auctions/<int:auction_id>/', admin_views.auction_detail, name='staff_admin_auction_detail'),
    path('admin-console/auctions/<int:auction_id>/cancel/', admin_views.cancel_auction, name='staff_admin_cancel_auction'),
    path('admin-console/reports/', admin_views.report_list, name='staff_admin_report_list'),
    path('admin-console/reports/<int:report_id>/', admin_views.report_detail, name='staff_admin_report_detail'),
    path('admin-console/reports/<int:report_id>/resolve/', admin_views.review_report, name='staff_admin_review_report'),
    path('admin-console/platform-reports/', admin_views.platform_reports, name='staff_admin_platform_reports'),
    path('admin-console/platform-analytics/', admin_views.platform_analytics, name='staff_admin_platform_analytics'),
    path('notifications/', views.notifications, name='notifications'),
    path(
        'notifications/<int:notification_id>/read/',
        views.mark_notification_read,
        name='mark_notification_read',
    ),
    path(
        'notifications/read-all/',
        views.mark_all_notifications_read,
        name='mark_all_notifications_read',
    ),

    # =====================================================
    # PROFILE
    # =====================================================

    path('profile/', views.profile, name='profile'),
    path('profile/edit/', views.edit_profile, name='edit_profile'),

    # =====================================================
    # BUYER / SELLER MODE
    # =====================================================

    path(
        'switch-mode/<str:mode>/',
        views.switch_mode,
        name='switch_mode'
    ),

    # =====================================================
    # BUYER - BROWSE AUCTIONS AND BIDDING
    # =====================================================

    path(
        'browse-auctions/',
        browse_views.browse_auctions,
        name='browse_auctions'
    ),

    path(
        'auction/<int:auction_id>/',
        browse_views.auction_detail,
        name='auction_detail'
    ),

    path(
        'auction/<int:auction_id>/bid/',
        browse_views.place_bid,
        name='place_bid'
    ),
    path('auction/<int:auction_id>/report/', browse_views.report_auction, name='report_auction'),

    path(
        'my-bids/',
        browse_views.my_bids,
        name='my_bids'
    ),
    path('my-watchlist/', browse_views.my_watchlist, name='my_watchlist'),
    path('recently-viewed/', browse_views.recently_viewed, name='recently_viewed'),
    path(
        'auction/<int:auction_id>/watchlist/add/',
        browse_views.add_to_watchlist,
        name='add_to_watchlist',
    ),
    path(
        'auction/<int:auction_id>/watchlist/remove/',
        browse_views.remove_from_watchlist,
        name='remove_from_watchlist',
    ),

    # =====================================================
    # SELLER - PRODUCTS
    # =====================================================

    path(
        'seller/products/add/',
        views.add_product,
        name='add_product'
    ),

    path(
        'seller/products/',
        views.seller_products,
        name='seller_products'
    ),

    path(
        'seller/products/edit/<int:product_id>/',
        views.edit_product,
        name='edit_product'
    ),
    path(
        'seller/products/<int:product_id>/manage/',
        views.manage_product,
        name='manage_product',
    ),

    path(
        'seller/products/image/delete/<int:image_id>/',
        views.delete_product_image,
        name='delete_product_image'
    ),

    # =====================================================
    # SELLER - AUCTIONS
    # =====================================================

    path(
        'seller/auction/create/<int:product_id>/',
        views.create_auction,
        name='create_auction'
    ),

    path(
        'seller/auctions/',
        views.seller_auctions,
        name='seller_auctions'
    ),

    path(
        'seller/auctions/edit/<int:auction_id>/',
        views.edit_auction,
        name='edit_auction'
    ),
    path('seller/received-bids/', views.received_bids, name='received_bids'),
    path('seller/winners/', views.seller_winners, name='seller_winners'),
    path('seller/analytics/', views.seller_analytics, name='seller_analytics'),
    path(
        'seller/auctions/<int:auction_id>/cancel/',
        views.cancel_auction,
        name='cancel_auction',
    ),
]


# =========================================================
# MEDIA FILES
# =========================================================

if settings.DEBUG:
    urlpatterns += static(
        settings.MEDIA_URL,
        document_root=settings.MEDIA_ROOT
    )
