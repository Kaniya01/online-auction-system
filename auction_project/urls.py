from django.contrib import admin
from django.urls import path
from django.conf import settings
from django.conf.urls.static import static

from auction import views
from auction import browse_views
from auction import payment_views


urlpatterns = [

    # =====================================================
    # ADMIN
    # =====================================================

    path(
        'admin/',
        admin.site.urls
    ),


    # =====================================================
    # HOME / DASHBOARD
    # =====================================================

    path(
        '',
        views.dashboard,
        name='home'
    ),

    path(
        'dashboard/',
        views.dashboard,
        name='dashboard'
    ),


    # =====================================================
    # AUTHENTICATION
    # =====================================================

    path(
        'register/',
        views.register,
        name='register'
    ),

    path(
        'login/',
        views.login_view,
        name='login'
    ),

    path(
        'logout/',
        views.logout_view,
        name='logout'
    ),


    # =====================================================
    # PROFILE
    # =====================================================

    path(
        'profile/',
        views.profile,
        name='profile'
    ),

    path(
        'profile/edit/',
        views.edit_profile,
        name='edit_profile'
    ),


    # =====================================================
    # BUYER / SELLER MODE
    # =====================================================

    path(
        'switch-mode/<str:mode>/',
        views.switch_mode,
        name='switch_mode'
    ),


    # =====================================================
    # BUYER - BROWSE AUCTIONS
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

    path(
        'my-bids/',
        browse_views.my_bids,
        name='my_bids'
    ),
    # =====================================================
# BUYER - PAYMENTS
# =====================================================

    path(
        'auction/<int:auction_id>/payment/',
        payment_views.make_payment,
        name='make_payment'
    ),

    path(
       'my-payments/',
       payment_views.my_payments,
       name='my_payments'
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


    # =====================================================
    # SELLER - CREATE AUCTION
    # =====================================================

    path(
        'seller/auction/create/<int:product_id>/',
        views.create_auction,
        name='create_auction'
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

    