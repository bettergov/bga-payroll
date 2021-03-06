from django.core.management.base import BaseCommand
from django.db.models import Sum, Q
import pysolr

from django.conf import settings

from data_import.models import StandardizedFile
from payroll.models import Employer, Person, Salary, Job


class Command(BaseCommand):
    help = 'Populate the Solr index'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.searcher = pysolr.Solr(settings.SOLR_URL)
        self.reporting_years = [x.reporting_year for x
                                in StandardizedFile.objects.distinct('reporting_year')]

    def add_arguments(self, parser):
        parser.add_argument(
            '--entity-types',
            dest='entity_types',
            help='Comma separated list of entity types to index',
            default='units,departments,people'
        )
        parser.add_argument(
            '--recreate',
            action='store_true',
            dest='recreate',
            default=False,
            help='Delete all existing documents before creating the search index'
        )
        parser.add_argument(
            '--chunksize',
            dest='chunksize',
            default=1000,
            help='Number of documents to add at once'
        )
        parser.add_argument(
            '--employer',
            default=None,
            help='ID of specific Employer instance to reindex'
        )
        parser.add_argument(
            '--person',
            default=None,
            help='ID of specific Person instance to reindex'
        )
        '''
        TO-DO: Implement these selective index building args, for version 2.
        If we're adding units and departments, we're going to want to rebuild
        the index for the entire year, since it's possible to receive employer
        data in more than one upload, i.e., the calculated expenditure and
        headcount fields may change & need updating. Conversely, people are
        always treated as distinct within a reporting year, so we could feasibly
        do that by upload, i.e., standardized file. Since we're only handling
        one year of data up front, however, let's just drop and rebuild the
        whole shebang when we import new data.
        '''
        parser.add_argument(
            '--s_file',
            dest='s_file_id',
            default=None,
            help='Specify a specific standardized file to index'
        )
        parser.add_argument(
            '--reporting_year',
            dest='reporting_year',
            default=None,
            help='Specify a specific reporting year to index'
        )

    def handle(self, *args, **options):
        if options['employer']:
            self.reindex_one('employer', options['employer'])

        elif options['person']:
            self.reindex_one('person', options['person'])

        else:
            self.recreate = options['recreate']
            self.chunksize = int(options['chunksize'])

            entities = options['entity_types'].split(',')

            for entity in entities:
                getattr(self, 'index_{}'.format(entity))()

    def _make_unit_index(self, unit):
        name = unit.name
        taxonomy = str(unit.taxonomy)

        of_unit = Q(job__position__employer=unit) | Q(job__position__employer__parent=unit)

        for year in self.reporting_years:
            in_year = Q(vintage__standardized_file__reporting_year=year)

            salaries = Salary.objects.filter(of_unit & in_year)
            expenditure = salaries.aggregate(expenditure=Sum('amount'))['expenditure']
            headcount = salaries.count()

            document = {
                'id': 'unit.{0}.{1}'.format(unit.id, year),
                'slug': unit.slug,
                'name': name,
                'entity_type': 'Employer',
                'year': year,
                'taxonomy_s': taxonomy,
                'size_class_s': unit.size_class,
                'expenditure_d': expenditure,
                'headcount_i': headcount,
                'text': name,
            }

            yield document

    def index_units(self):
        if self.recreate:
            self.stdout.write('Dropping units from index')
            self.searcher.delete(q='id:unit*')
            self.stdout.write(self.style.SUCCESS('Units dropped from index'))

        self.stdout.write('Indexing units')

        documents = []
        document_count = 0

        units = Employer.objects.filter(parent_id__isnull=True)

        for unit in units:
            for document in self._make_unit_index(unit):
                documents.append(document)

                if len(documents) == self.chunksize:
                    self.searcher.add(documents)
                    document_count += len(documents)
                    documents = []

        if documents:
            self.searcher.add(documents)
            document_count += len(documents)

        success_message = 'Added {0} documents for {1} units to the index'.format(document_count,
                                                                                  units.count())

        self.stdout.write(self.style.SUCCESS(success_message))

    def _make_department_index(self, department):
        name = str(department)

        of_department = Q(job__position__employer=department)

        for year in self.reporting_years:
            in_year = Q(vintage__standardized_file__reporting_year=year)

            salaries = Salary.objects.filter(of_department & in_year)
            expenditure = salaries.aggregate(expenditure=Sum('amount'))['expenditure']
            headcount = salaries.count()

            document = {
                'id': 'department.{0}.{1}'.format(department.id, year),
                'slug': department.slug,
                'name': name,
                'entity_type': 'Employer',
                'year': year,
                'expenditure_d': expenditure,
                'headcount_i': headcount,
                'parent_s': department.parent.slug,
                'text': name,
            }

            if department.universe:
                document['universe_s'] = str(department.universe)

            yield document

    def index_departments(self):
        if self.recreate:
            self.stdout.write('Dropping departments from index')
            self.searcher.delete(q='id:department*')
            self.stdout.write(self.style.SUCCESS('Departments dropped from index'))

        self.stdout.write('Indexing departments')

        documents = []
        document_count = 0

        departments = Employer.objects.filter(parent_id__isnull=False)

        for department in departments:
            for document in self._make_department_index(department):
                documents.append(document)

                if len(documents) == self.chunksize:
                    self.searcher.add(documents)
                    document_count += len(documents)
                    documents = []

        if documents:
            self.searcher.add(documents)
            document_count += len(documents)

        success_message = 'Added {0} documents for {1} departments to the index'.format(document_count,
                                                                                        departments.count())

        self.stdout.write(self.style.SUCCESS(success_message))

    def _make_person_index(self, person):
        name = str(person)

        for year in self.reporting_years:
            try:
                job = person.jobs.select_related('position', 'position__employer')\
                                 .prefetch_related('salaries')\
                                 .get(vintage__standardized_file__reporting_year=year)

            except Job.DoesNotExist:
                # It's reasonable to expect every person won't appear in
                # every year of data.
                continue

            except Job.MultipleObjectsReturned:
                # A very, very small minority of people (less than 20) in
                # the full 2017 data I'm using for testing were imported
                # such that they have more than one job. I'm not totally
                # certain why, but I suspect edge cases, e.g., Governors
                # State University reported payroll itself, and was also
                # reported by the state board of higher education.
                #
                # I've opened an issue to investigate these edge cases. In
                # the meantime, I'm just going to log these inconsistencies
                # (there's no guarantee they'll recur in the new data any-
                # way) and add only one of the jobs to the index.
                job_str = ', '.join('{0} for {1}'.format(
                    j.position.title, j.position.employer) for j in person.jobs.all()
                )

                info = '{0} (#{1}) has more than one job in {2}: {3}'.format(name,
                                                                             person.id,
                                                                             year,
                                                                             job_str)
                self.stdout.write(self.style.NOTICE(info))

                job = person.jobs.select_related('position', 'position__employer')\
                                 .prefetch_related('salaries')\
                                 .first()

            position = job.position
            employer = position.employer

            text = '{0} {1} {2}'.format(name, employer, position)

            if employer.is_department:
                employer_slug = [employer.parent.slug, employer.slug]
            else:
                employer_slug = [employer.slug]

            document = {
                'id': 'person.{0}.{1}'.format(person.id, year),
                'slug': person.slug,
                'name': name,
                'entity_type': 'Person',
                'year': year,
                'title_s': job.position.title,
                'salary_d': job.salaries.get().amount,
                'employer_ss': employer_slug,
                'text': text,
            }

            yield document

    def index_people(self):
        if self.recreate:
            self.stdout.write('Dropping people from index')
            self.searcher.delete(q='id:person*')
            self.stdout.write(self.style.SUCCESS('People dropped from index'))

        self.stdout.write('Indexing people')

        documents = []
        document_count = 0

        people = Person.objects.all()

        for person in people:
            for document in self._make_person_index(person):
                documents.append(document)

                if len(documents) == self.chunksize:
                    self.searcher.add(documents)
                    document_count += len(documents)
                    documents = []

        if documents:
            self.searcher.add(documents)
            document_count += len(documents)

        success_message = 'Added {0} documents for {1} people to the index'.format(document_count,
                                                                                   people.count())

        self.stdout.write(self.style.SUCCESS(success_message))

    def reindex_one(self, entity_type, entity_id):
        entity_model_map = {
            'employer': Employer,
            'person': Person,
        }

        update_object = entity_model_map[entity_type].objects.get(id=entity_id)
        id_kwargs = {'id': entity_id}

        if isinstance(update_object, Employer):
            if update_object.is_department:
                index_func = self._make_department_index
                id_kwargs['type'] = 'department'
            else:
                index_func = self._make_unit_index
                id_kwargs['type'] = 'unit'

        elif isinstance(update_object, Person):
            index_func = self._make_person_index
            id_kwargs['type'] = 'person'

        index_id = '{type}.{id}*'.format(**id_kwargs)

        self.stdout.write('Dropping {} from index'.format(update_object))
        self.searcher.delete(q=index_id)
        self.stdout.write(self.style.SUCCESS('{} dropped from index'.format(update_object)))

        documents = []

        for document in index_func(update_object):
            documents.append(document)

        self.searcher.add(documents)

        success_message = 'Added {0} documents for {1} to the index'.format(len(documents),
                                                                            update_object)

        self.stdout.write(self.style.SUCCESS(success_message))
