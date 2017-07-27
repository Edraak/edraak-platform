
try:
    from wand.image import Image
except ImportError:  # Usually an exception that suggests to `$ apt-get install libmagickwand-dev`.
    # Avoid installing the OS dependency inside test workers.
    # This helps to maintain clean test workers.
    # As long as the modules are importing it using the syntax: `from wand.image import Image`.
    from edraak_certificates.tests import wand_image_mock
    import sys
    sys.modules['wand.image'] = wand_image_mock
