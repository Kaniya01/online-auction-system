from django.contrib import admin
from django.urls import path
from django.contrib.auth import views as auth_views
from django.conf import settings
from django.conf.urls.static import static

from auction import views
from auction import browse_views


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
