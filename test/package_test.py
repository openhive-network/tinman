import importlib.resources
import unittest


class PackageTest(unittest.TestCase):
    def test_server_assets_are_packaged(self):
        package_root = importlib.resources.files("tinman")
        self.assertTrue(package_root.joinpath("templates/account_create.html").is_file())
        self.assertTrue(package_root.joinpath("static/bootstrap.min.css").is_file())
