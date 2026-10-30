from django.http import JsonResponse


class SecurityHeadersMiddleware:
    """Extra browser security headers on top of Django's SecurityMiddleware."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        response.setdefault('Permissions-Policy', 'camera=(), microphone=(), geolocation=(), payment=()')
        if request.path.startswith('/api/'):
            # API answers are data, never pages: nothing may run or be framed,
            # and personal data must not be stored in browser/proxy caches.
            response.setdefault('Content-Security-Policy', "default-src 'none'; frame-ancestors 'none'")
            response.setdefault('Cache-Control', 'no-store')
        return response


class PasswordChangeRequiredMiddleware:
    """Someone signed in with a temporary password (new account or admin reset) can only
    use the /api/auth/ endpoints - i.e. change their password or sign out - until they pick their own.
    After that, until they fill in their travel profile, they can also use /api/profile/ and nothing else."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        path = request.path
        if path.startswith('/api/') and not path.startswith('/api/auth/'):
            user = getattr(request, 'user', None)
            if user is not None and user.is_authenticated:
                profile = getattr(user, 'profile', None)
                if profile is not None and profile.must_change_password:
                    return JsonResponse(
                        {'detail': 'Please change your temporary password first.',
                         'code': 'password_change_required'}, status=403)
                if (profile is not None and profile.profile_completed_at is None
                        and not path.startswith('/api/profile/')):
                    return JsonResponse(
                        {'detail': 'Please complete your profile first.', 'code': 'profile_required'}, status=403)
        return self.get_response(request)
