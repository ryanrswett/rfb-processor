"""Scanline and Luhn check digit generation.

Replicates the C# MakeScanLine logic:
  baseValue = acquisitionId + donorId + keyCodeListId
  checkDigit = Luhn.CalculateCheckDigit(baseValue)
  fullScan = baseValue + checkDigit
"""


def luhn_check_digit(number_str: str) -> str:
    """Calculate Luhn check digit for a numeric string."""
    digits = [int(d) for d in number_str]
    # Double every second digit from the right
    for i in range(len(digits) - 1, -1, -2):
        digits[i] *= 2
        if digits[i] > 9:
            digits[i] -= 9
    total = sum(digits)
    check = (10 - (total % 10)) % 10
    return str(check)


def make_scanline(
    acquisition_id: str, donor_id: str, key_code_list_id: str
) -> tuple[str, str]:
    """Build scanline from components, returns (full_scanline, check_digit)."""
    base_value = f"{acquisition_id}{donor_id}{key_code_list_id}"
    check_digit = luhn_check_digit(base_value)
    return base_value + check_digit, check_digit
