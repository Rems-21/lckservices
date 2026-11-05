"""
Backend MySQL / InnoDB compatible MySQL 8+ et environnements locaux XAMPP/MariaDB sous Windows.
"""
from django.db.backends.mysql import base as mysql_base
from django.db.backends.mysql.features import DatabaseFeatures as MySQLDatabaseFeatures
from django.utils.functional import cached_property


class DatabaseFeatures(MySQLDatabaseFeatures):
    @cached_property
    def minimum_database_version(self):
        if self.connection.mysql_is_mariadb:
            return (10, 4)
        return (8, 0, 11)

    @cached_property
    def can_return_columns_from_insert(self):
        if self.connection.mysql_is_mariadb and self.connection.mysql_version < (10, 5):
            return False
        return super().can_return_columns_from_insert

    @cached_property
    def can_return_rows_from_bulk_insert(self):
        if self.connection.mysql_is_mariadb and self.connection.mysql_version < (10, 5):
            return False
        return super().can_return_rows_from_bulk_insert


class DatabaseWrapper(mysql_base.DatabaseWrapper):
    features_class = DatabaseFeatures
