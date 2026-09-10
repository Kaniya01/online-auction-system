from django.contrib import admin
from django.urls import path
from django.conf import settings
from django.conf.urls.static import static

from auction import views


urlpatterns = [
    path('admin/', admin.site.urls),

    # Home page
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
    path('register/', views.register, name='register'),
    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),
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
    'seller/auction/create/<int:product_id>/',
    views.create_auction,
    name='create_auction'
),
]


if settings.DEBUG:
    urlpatterns += static(
        settings.MEDIA_URL,
        document_root=settings.MEDIA_ROOT
    )