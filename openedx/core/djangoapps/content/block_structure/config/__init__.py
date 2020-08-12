"""
This module contains various configuration settings via
waffle switches for the Block Structure framework.
"""
from openedx.core.djangoapps.waffle_utils import WaffleSwitchNamespace
from openedx.core.lib.cache_utils import request_cached

from .models import BlockStructureConfiguration


# Namespace
WAFFLE_NAMESPACE = u'block_structure'

# Switches
INVALIDATE_CACHE_ON_PUBLISH = u'invalidate_cache_on_publish'
STORAGE_BACKING_FOR_CACHE = u'storage_backing_for_cache'
RAISE_ERROR_WHEN_NOT_FOUND = u'raise_error_when_not_found'


def waffle():
    """
    Returns the namespaced and cached Waffle class for BlockStructures.
    """
    return WaffleSwitchNamespace(name=WAFFLE_NAMESPACE, log_prefix=u'BlockStructure: ')


@request_cached()
def num_versions_to_keep():
    """
    Returns and caches the current setting for num_versions_to_keep.
    """
    return BlockStructureConfiguration.current().num_versions_to_keep


@request_cached()
def cache_timeout_in_seconds():
    """
    Returns and caches the current setting for cache_timeout_in_seconds.
    """
    return BlockStructureConfiguration.current().cache_timeout_in_seconds
