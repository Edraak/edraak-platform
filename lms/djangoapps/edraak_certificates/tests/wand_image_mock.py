"""
A mock for the `wand.image` module in case the MagicWand library was missing from the OS.
"""


class Image(object):
    """
    A Mock to the `wand.image.Magic` for tests, to avoid relying on the OS library.
    """

    def __init__(self, filename=None, content=None):
        """
        This is limited to what we need at the Edraak certificate module, feel free to extend to other parameters
        when needed.
        """
        self.filename = filename
        self.content = content

        if filename:
            with open(filename) as input_file:  # Make sure the file is legit!
                self.content = input_file.read()

    def clone(self):
        """
        Creates a clone instance!
        """
        new_image = Image(content=self.content)
        return new_image

    def __enter__(self):
        """
        Become compatible with the `wand.image.Magic`.
        """
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """
        Do some stupid clean up, to act like we're destroying something.
        """
        self.content = None

    def save(self, filename):
        """
        Pretend to save something!
        """
        pass
