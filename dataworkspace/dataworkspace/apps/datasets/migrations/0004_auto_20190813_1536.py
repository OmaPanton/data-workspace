# Generated by Django 2.2.3 on 2019-08-13 15:36

from django.db import migrations, connection, ProgrammingError


def generate_table_name(apps, _):
    model = apps.get_model('datasets', 'ReferenceDataset')
    for r in model.objects.all():
        r._original_table_name = 'refdata__{}'.format(r.id)
        if r.table_name is None or r.table_name == r._original_table_name:
            r.table_name = 'ref_{}'.format(r.slug.replace('-', '_'))
            print('Changing table "{}" to "{}"'.format(r._original_table_name, r.table_name))
            r.schema_version += 1
            r.save()
            with connection.schema_editor() as editor:
                try:
                    editor.alter_db_table(model, r._original_table_name, r.table_name)
                except ProgrammingError:
                    pass


class Migration(migrations.Migration):

    dependencies = [
        ('datasets', '0003_referencedataset_table_name'),
    ]

    operations = [
        migrations.RunPython(
            generate_table_name, reverse_code=migrations.RunPython.noop
        )
    ]
