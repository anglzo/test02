def total(items):
    """Suma precios con IVA."""
    return sum(i['precio']*1.16 for i in items)
