"""
One-off script to rehash all retired usernames in UserRetirementStatus and auth_user.
Background: We discovered that all prior retired usernames were generated based on
the exact capitalization of the original username, despite the fact that
usernames are considered case insensitive in practice.  This led to the
possibility of users registering accounts with effectively retired usernames just
by changing the capitalization of the username, because the different
capitalization would hash to a different digest.
Solution: Rehash all usernames using the normalized-case (lowercase)
original usernames rather than the possibly mixed-case ones.  This management
command likely cannot be re-used in the future because eventually we will need
to clean out the UserRetirementStatus table.
"""
from __future__ import print_function

from django.conf import settings
from django.db import transaction
from django.core.management.base import BaseCommand
from six import text_type

from lms.lib import comment_client
from openedx.core.djangoapps.user_api.models import UserRetirementStatus
from user_util import user_util


class Command(BaseCommand):
    """
    Implementation of the bulk_rehash_retired_usernames command.
    """
    def add_arguments(self, parser):
        parser.add_argument(
            '--dry_run',
            action='store_true',
            help='Print proposed changes, but take no action.'
        )

    def handle(self, *args, **options):
        """
        Execute the command.
        """
        dry_run = options['dry_run']
        retirements = UserRetirementStatus.objects.all().select_related('user')

        failed_retirements = []
        for retirement in retirements:
            original_username = retirement.original_username
            old_retired_username = retirement.retired_username
            new_retired_username = user_util.get_retired_username(
                original_username,
                settings.RETIRED_USER_SALTS,
                settings.RETIRED_USERNAME_FMT
            )

            # If the original username was already normalized (or all lowercase), the old and new hashes would
            # match:
            if old_retired_username == new_retired_username:
                print(
                    'Skipping UserRetirementStatus ID {} / User ID {} because the hash would not change.'.format(
                        retirement.id,
                        retirement.user.id,
                    )
                )
            # Found an username to update
            else:
                print(
                    'Updating UserRetirementStatus ID {} / User ID {} '
                    'to rehash their retired username: {} -> {}'.format(
                        retirement.id,
                        retirement.user.id,
                        old_retired_username,
                        new_retired_username
                    )
                )
                if not dry_run:
                    try:
                        # Update the forums first, that way if it fails the user can
                        # be re-run. It does not need to be in the same transaction,
                        # as the local db updates and can be slow, so keeping it
                        # outside to cut down on potential deadlocks.
                        cc_user = comment_client.User.from_django_user(retirement.user)

                        # The user may not exist in forums, if it doesn't that's not
                        # an error.
                        try:
                            cc_user.retire(new_retired_username)
                        except comment_client.utils.CommentClientRequestError as e:
                            if e.status_code != 404:
                                print(
                                    'UserRetirementStatus ID {} User ID {} failed to rename in forums: {}'.format(
                                        retirement.id, retirement.user.id, text_type(e)
                                    )
                                )
                                raise

                        # Update and save both the user table and retirement queue table:
                        with transaction.atomic():
                            # Only rename them in auth_user if they've already been retired
                            if retirement.user.username == old_retired_username:
                                retirement.user.username = new_retired_username
                                retirement.user.save()
                            retirement.retired_username = new_retired_username
                            retirement.save()
                    except Exception as exc:  # pylint: disable=broad-except
                        print(
                            'UserRetirementStatus ID {} User ID {} failed rename'.format(
                                retirement.id, retirement.user.id
                            )
                        )
                        print(text_type(exc))
                        failed_retirements.append(retirement)

        if failed_retirements:
            print('------------------------------------------------------------')
            print(
                'FAILED! {} retirements failed to rehash. Retirement IDs:\n{}'.format(
                    len(failed_retirements),
                    '\n'.join([text_type(r.id) for r in failed_retirements])
                )
            )
        else:
            print('Success! {} retirements examined.'.format(len(retirements)))
