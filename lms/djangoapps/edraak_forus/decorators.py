def setfuncattr(name, value): # pylint: disable=invalid-name
    def inner(func):
        setattr(func, name, value)
        return func

    return inner