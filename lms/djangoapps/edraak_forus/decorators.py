"""
Function used as a decorator to set methods certain keys values
"""


def setfuncattr(name, value):  # pylint: disable=invalid-name
    """
    Returns inner function with key-value pair set
    """
    def inner(func):
        """
        Return func with name:value pair
        """
        setattr(func, name, value)
        return func

    return inner
