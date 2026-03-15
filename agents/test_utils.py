"""
Unit tests for utils.py
"""
import unittest
from utils import add, sub

class TestUtils(unittest.TestCase):
    def test_add(self):
        """Test add function with various inputs"""
        self.assertEqual(add(1, 2), 3)
        self.assertEqual(add(-1, 1), 0)
        self.assertEqual(add(0, 0), 0)
        self.assertEqual(add(1.5, 2.5), 4.0)

    def test_sub(self):
        """Test sub function with various inputs"""
        self.assertEqual(sub(3, 2), 1)
        self.assertEqual(sub(1, 1), 0)
        self.assertEqual(sub(0, 5), -5)
        self.assertEqual(sub(5.5, 2.5), 3.0)

if __name__ == '__main__':
    unittest.main()