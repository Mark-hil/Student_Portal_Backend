"""Route reads to replica, writes to primary."""


import sys
from django.conf import settings


class PrimaryReplicaRouter:
    def db_for_read(self, model, **hints):
        if "replica" not in settings.DATABASES or "pytest" in sys.modules:
            return "default"
        return "replica"

    def db_for_write(self, model, **hints):
        return "default"

    def allow_relation(self, obj1, obj2, **hints):
        return True

    def allow_migrate(self, db, app_label, model_name=None, **hints):
        return db == "default"
