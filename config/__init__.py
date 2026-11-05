"""Configuration centrale du projet LCK Services SARL."""
try:
    import MySQLdb  # noqa: F401
except ImportError:
    try:
        import pymysql

        pymysql.version_info = (2, 2, 4, "final", 0)
        pymysql.install_as_MySQLdb()
    except ImportError:
        pass
