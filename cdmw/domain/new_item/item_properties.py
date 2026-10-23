"""Closed scalar overrides for an independently authored equipment item."""

PROPERTY_LIMITS = {'item_tier': 0xff, 'required_level': 0xffffffff, 'max_durability': 0xffff}


def property_values(spec):
    return {name: getattr(spec, name) for name in PROPERTY_LIMITS}


def checked_properties(data):
    if not isinstance(data, dict) or set(data) != set(PROPERTY_LIMITS):
        raise ValueError('Unsupported item property fields.')
    for name, maximum in PROPERTY_LIMITS.items():
        value = data[name]
        if value is not None and (type(value) is not int or not 0 <= value <= maximum):
            raise ValueError(f'{name} must be an integer in 0..{maximum}, or inherit the template.')
    if all(value is None for value in data.values()):
        raise ValueError('An item properties module must contain an explicit override.')
    return dict(data)
