from django.db import migrations

from apps.billing.plans import DEFAULT_PLANS


def create_plans(apps, schema_editor):
    Plan = apps.get_model("billing", "Plan")
    for data in DEFAULT_PLANS:
        Plan.objects.update_or_create(code=data["code"], defaults=data)


class Migration(migrations.Migration):
    dependencies = [("billing", "0001_initial")]

    operations = [migrations.RunPython(create_plans, migrations.RunPython.noop)]
