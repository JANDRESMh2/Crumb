from django.contrib import messages
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.shortcuts import redirect, render
from django.utils.dateparse import parse_date

from .decorators import bakery_required
from .forms import BakeryProfileForm
from .models import ActivityLog
from .services import (
    BakeryAlreadyConfigured,
    build_activity_log,
    get_current_bakery,
    setup_bakery_profile,
    update_bakery_profile,
)

ACTIVITY_LOG_PAGE_SIZE = 100


def bakery_setup(request):
    """FR09 - register the bakery's business profile during initial setup."""
    if get_current_bakery() is not None:
        return redirect('bakery:detail')

    if request.method == 'POST':
        form = BakeryProfileForm(request.POST)
        if form.is_valid():
            try:
                setup_bakery_profile(**form.cleaned_data)
            except BakeryAlreadyConfigured:
                messages.warning(request, 'The bakery profile was already set up.')
                return redirect('bakery:detail')
            messages.success(request, 'Business profile created successfully.')
            return redirect('bakery:detail')
    else:
        form = BakeryProfileForm()

    return render(request, 'bakery/setup.html', {'form': form})


@bakery_required()
def bakery_detail(request):
    bakery = request.bakery
    return render(request, 'bakery/detail.html', {'bakery': bakery})
@bakery_required()
def bakery_edit(request):
    bakery = request.bakery

    if request.method == 'POST':
        form = BakeryProfileForm(request.POST, instance=bakery)
        if form.is_valid():
            update_bakery_profile(bakery, **form.cleaned_data)
            messages.success(request, 'Business profile updated successfully.')
            return redirect('bakery:detail')
    else:
        form = BakeryProfileForm(instance=bakery)

    return render(request, 'bakery/edit.html', {'form': form, 'bakery': bakery})


@bakery_required('Set up the bakery profile before reviewing the activity log.')
def activity_log(request):
    """FR28 - review what each user did in the system."""

    bakery = request.bakery

    action_type = request.GET.get('action_type', '').strip()
    user_id = request.GET.get('user', '').strip()
    start_date = request.GET.get('start_date', '').strip()
    end_date = request.GET.get('end_date', '').strip()

    if action_type not in ActivityLog.ActionType.values:
        action_type = ''

    users = (
        get_user_model().objects
        .filter(activity_logs__isnull=False)
        .distinct()
        .order_by('username')
    )

    user = None
    if user_id.isdigit():
        user = users.filter(pk=int(user_id)).first()
    if user is None:
        user_id = ''

    try:
        entries = build_activity_log(
            user=user,
            action_type=action_type,
            start_date=parse_date(start_date) if start_date else None,
            end_date=parse_date(end_date) if end_date else None,
        )
        total = entries.count()
        entries = list(entries[:ACTIVITY_LOG_PAGE_SIZE])
    except (ValidationError, ValueError) as error:
        messages.error(
            request,
            ' '.join(getattr(error, 'messages', ['Invalid date.'])),
        )
        entries, total = [], 0

    return render(
        request,
        'bakery/activity_log.html',
        {
            'bakery': bakery,
            'entries': entries,
            'total': total,
            'hidden': max(total - len(entries), 0),
            'users': users,
            'action_types': ActivityLog.ActionType.choices,
            'action_type': action_type,
            'user_id': user_id,
            'start_date': start_date,
            'end_date': end_date,
            'has_filters': bool(
                action_type or user_id or start_date or end_date
            ),
        },
    )
