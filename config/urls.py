"""
Root URL configuration for AI Video Engine.
"""

from django.contrib import admin
from django.urls import path, include, re_path
from django.conf import settings
from django.conf.urls.static import static
from django.http import HttpResponse
from django.views.static import serve
import os

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/', include('apps.core.api.urls')),
]


# ── Dashboard (React SPA) ──

def dashboard_view(request):
    """Serve the React dashboard index.html."""
    index_path = os.path.join(settings.DASHBOARD_DIR, 'index.html')
    if os.path.exists(index_path):
        with open(index_path, 'r') as f:
            return HttpResponse(f.read(), content_type='text/html')
    return HttpResponse(
        '<h1>Dashboard not built</h1>'
        '<p>Run <code>cd dashboard && npm run build</code> first.</p>',
        content_type='text/html',
        status=404,
    )

urlpatterns += [
    # Serve built dashboard assets (JS, CSS) at /dashboard/static/
    re_path(
        r'^dashboard/static/(?P<path>.*)$',
        serve,
        {'document_root': str(settings.DASHBOARD_DIR)},
    ),
    # Serve the SPA entry point at /dashboard/
    path('dashboard/', dashboard_view, name='dashboard'),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
