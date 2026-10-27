from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import Organization, User


@admin.register(User)
class InvoiceFlowUserAdmin(UserAdmin):
    fieldsets = (*UserAdmin.fieldsets, ("Organisation", {"fields": ("organization",)}))
    list_display = ("username", "email", "organization", "is_staff")
    list_filter = ("organization", *UserAdmin.list_filter)


@admin.register(Organization)
class OrganizationAdmin(admin.ModelAdmin):
    list_display = ("name", "abn", "created_at")
    search_fields = ("name", "abn")
