"""
A mock for the `wand.image` module in case the MagicWand library was missing from the OS.
"""


class Image(object):
    """
    A Mock to the `wand.image.Magic` for tests, to avoid relying on the OS library.
    """

    def __init__(self, file=None):
        """
        This is limited to what we need at the Edraak certificate module, feel free to extend to other parameters
        when needed.
        """
        self.file = file

    def clone(self):
        """
        Creates a clone instance!
        """
        new_image = Image(file=self.file)
        return new_image

    def save(self, file):
        """
        Pretend to save something!
        """
        pass
