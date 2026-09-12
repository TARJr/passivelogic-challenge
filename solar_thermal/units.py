"""Display conversions. Model inputs and stored results retain their SI units."""

LITERS_PER_US_GALLON = 3.785411784


def celsius_to_fahrenheit(value):
    return value * 9 / 5 + 32


def liters_to_us_gallons(value):
    return value / LITERS_PER_US_GALLON


def mass_flow_to_us_gpm(kg_s, density_kg_m3):
    return kg_s / density_kg_m3 * 1000 * 60 / LITERS_PER_US_GALLON
