import unittest

from normalizer import (
    classify_mitigation_type,
    clean_and_normalize_loading,
    parse_facility_metadata,
)


# __main__ samples, plus <100%, NotConv, and a per-unit voltage.
# Non-numeric rows must keep parsed_value null so "<100" is never stored as 100.
LOADING_CASES = [
    ("119.0%", 119.0, "OVERLOAD"),
    ("<100", None, "BELOW_LIMIT"),
    ("< 100", None, "BELOW_LIMIT"),
    ("< 80", None, "BELOW_LIMIT"),
    ("<100%", None, "BELOW_LIMIT"),
    ("NotConv", None, "NOT_CONVERGED"),
    ("NatConv", None, "NOT_CONVERGED"),
    ("95.5%", 95.5, "NORMAL"),
    ("1.05", 1.05, "VOLTAGE_PU"),
]

# PSLF bus pair: from-bus, name, kV, to-bus, name, kV, circuit, section.
PSLF_BUS_PAIR = "24156 Lugo 500 24157 Eldorado 500 1 1"

STORAGE_MITIGATION = (
    "Install a 100 MW battery energy storage system at the Mira Loma substation."
)


class NormalizerTests(unittest.TestCase):
    def test_loading_cases(self):
        for raw, expected_parsed, expected_status in LOADING_CASES:
            with self.subTest(raw=raw):
                parsed, status = clean_and_normalize_loading(raw)
                self.assertEqual(status, expected_status)
                if expected_parsed is None:
                    self.assertIsNone(parsed, "parsed value is null")
                else:
                    self.assertEqual(parsed, expected_parsed)

    def test_storage_mitigation_sentence(self):
        self.assertEqual(
            classify_mitigation_type(STORAGE_MITIGATION),
            "General Mitigation",
        )

    def test_pslf_style_bus_pair(self):
        name, voltage_kv, facility_type = parse_facility_metadata(PSLF_BUS_PAIR)
        self.assertEqual(name, PSLF_BUS_PAIR)
        self.assertEqual(voltage_kv, 500.0)
        self.assertEqual(facility_type, "Transmission Line")


if __name__ == "__main__":
    unittest.main()
