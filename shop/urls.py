"""Маршруты приложения shop."""
from django.contrib.auth import views as auth_views
from django.urls import path, reverse_lazy

from . import views

app_name = 'shop'

urlpatterns = [
    path('', views.home, name='home'),
    path('catalog/', views.catalog, name='catalog'),
    path('categories/', views.categories, name='categories'),
    path('categories/<slug:slug>/', views.category_detail, name='category_detail'),
    path('product/<int:pk>/', views.product_detail, name='product_detail'),
    path('product/<int:pk>/review/', views.review_add, name='review_add'),
    path('wishlist/', views.wishlist, name='wishlist'),
    path('wishlist/toggle/<int:pk>/', views.favorite_toggle, name='favorite_toggle'),
    path('cart/', views.cart_detail, name='cart'),
    path('cart/add/<int:pk>/', views.cart_add, name='cart_add'),
    path('cart/update/<int:pk>/', views.cart_update, name='cart_update'),
    path('cart/remove/<int:pk>/', views.cart_remove, name='cart_remove'),
    path('cart/clear/', views.cart_clear, name='cart_clear'),
    path('cart/coupon/', views.coupon_apply, name='coupon_apply'),
    path('cart/coupon/remove/', views.coupon_remove, name='coupon_remove'),
    path('checkout/', views.checkout, name='checkout'),
    path('order/success/', views.order_success, name='order_success'),
    path('order/<str:order_number>/receipt/', views.order_receipt, name='order_receipt'),
    path('accounts/register/', views.register, name='register'),
    path('accounts/login/', views.user_login, name='login'),
    path('accounts/logout/', views.user_logout, name='logout'),
    path('accounts/profile/', views.profile, name='profile'),
    path('accounts/profile/edit/', views.profile_edit, name='profile_edit'),
    path('accounts/password/', views.password_change, name='password_change'),
    path('accounts/orders/<str:order_number>/', views.order_detail, name='order_detail'),
    path(
        'accounts/orders/<str:order_number>/cancel/',
        views.order_cancel,
        name='order_cancel',
    ),
    path(
        'accounts/password-reset/',
        auth_views.PasswordResetView.as_view(
            template_name='registration/password_reset_form.html',
            email_template_name='registration/password_reset_email.html',
            subject_template_name='registration/password_reset_subject.txt',
            success_url=reverse_lazy('shop:password_reset_done'),
        ),
        name='password_reset',
    ),
    path(
        'accounts/password-reset/sent/',
        auth_views.PasswordResetDoneView.as_view(
            template_name='registration/password_reset_done.html',
        ),
        name='password_reset_done',
    ),
    path(
        'accounts/password-reset/<uidb64>/<token>/',
        auth_views.PasswordResetConfirmView.as_view(
            template_name='registration/password_reset_confirm.html',
            success_url=reverse_lazy('shop:password_reset_complete'),
        ),
        name='password_reset_confirm',
    ),
    path(
        'accounts/password-reset/done/',
        auth_views.PasswordResetCompleteView.as_view(
            template_name='registration/password_reset_complete.html',
        ),
        name='password_reset_complete',
    ),
    path('about/', views.about, name='about'),
    path('contacts/', views.contacts, name='contacts'),
]
