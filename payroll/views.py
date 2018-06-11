from itertools import chain
import json

from django.contrib.postgres.search import SearchVector
from django.db import connection
from django.db.models import Q, Sum, FloatField
from django.http import JsonResponse
from django.shortcuts import render, redirect
from django.urls import reverse
from django.views.generic.detail import DetailView
from django.views.generic.list import ListView
from postgres_stats.aggregates import Percentile

import numpy as np

from payroll.models import Employer, Job, Person, Salary
from payroll.utils import format_ballpark_number


def index(request):
    return render(request, 'index.html')


def error(request, error_code):
    return render(request, '{}.html'.format(error_code))


def person(request, slug):
    try:
        person = Person.objects.get(slug=slug)

    except Employer.DoesNotExist:
        error_page = reverse(error, kwargs={'error_code': 404})
        return redirect(error_page)

    return render(request, 'person.html', {
        'entity': person,
    })


class EmployerView(DetailView):
    template_name = 'employer.html'
    model = Employer
    context_object_name = 'entity'

    from_clause = '''
        FROM payroll_job AS job
        JOIN payroll_salary AS salary
        ON salary.job_id = job.id
        JOIN payroll_position AS position
        ON job.position_id = position.id
        JOIN payroll_employer AS employer
        ON position.employer_id = employer.id
    '''

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        employee_salaries = self.employee_salaries()
        binned_employee_salaries = self.bin_salary_data(employee_salaries)

        context.update({
            'jobs': Job.of_employer(self.object.id, n=5),
            'median_salary': self.median_entity_salary(),
            'headcount': len(employee_salaries),
            'total_expenditure': sum(employee_salaries),
            'employee_salary_json': json.dumps(binned_employee_salaries),
        })

        if not self.object.is_department:
            department_statistics = self.aggregate_department_statistics()
            department_salaries = [d['amount'] for d in department_statistics]
            binned_department_salaries = self.bin_salary_data(department_salaries)

            context.update({
                'department_salaries': department_statistics[:5],
                'department_salary_json': json.dumps(binned_department_salaries),
            })

        return context

    @property
    def where_clause(self):
        if self.object.is_department:
            return '''
                WHERE employer.id = {id}
            '''.format(id=self.object.id)

        else:
            return '''
                WHERE employer.id = {id}
                OR employer.parent_id = {id}
            '''.format(id=self.object.id)

    def _make_query(self, query_fmt):
        return query_fmt.format(
            from_clause=self.from_clause,
            where_clause=self.where_clause,
        )

    def median_entity_salary(self):

        if self.object.parent is None:
            q = Salary.objects.filter(job__position__employer__parent=self.object)
        else:
            q = Salary.objects.filter(job__position__employer=self.object)

        results = q.all().aggregate(median=Percentile('amount', 0.5, output_field=FloatField()))

        return results['median']

    def aggregate_department_statistics(self):
        query = self._make_query('''
            SELECT
                employer.name,
                AVG(salary.amount) AS average,
                SUM(salary.amount) AS budget,
                COUNT(*) AS headcount,
                employer.slug AS slug
            {from_clause}
            {where_clause}
            GROUP BY employer.id, employer.name
            ORDER BY SUM(salary.amount) DESC
        ''')

        with connection.cursor() as cursor:
            cursor.execute(query)

            department_salaries = []

            for department, average, budget, headcount, slug in cursor:
                department_salaries.append({
                    'department': department,
                    'amount': average,
                    'total_budget': budget,
                    'headcount': headcount,
                    'slug': slug,
                })

        return department_salaries

    def employee_salaries(self):
        query = self._make_query('''
            SELECT
                salary.amount
            {from_clause}
            {where_clause}
        ''')

        with connection.cursor() as cursor:
            cursor.execute(query)

            employee_salaries = [row[0] for row in cursor]

        return employee_salaries

    def bin_salary_data(self, data):
        float_data = np.asarray(data, dtype='float')
        values, edges = np.histogram(float_data, bins=6)

        salary_json = []

        for i, value in enumerate(values):
            lower, upper = int(edges[i]), int(edges[i + 1])

            salary_json.append({
                'value': int(value),
                'lower_edge': format_ballpark_number(lower),
                'upper_edge': format_ballpark_number(upper),
            })

        return salary_json


class SearchView(ListView):
    queryset = []
    template_name = 'search_results.html'
    context_object_name = 'results'
    paginate_by = 25

    def get_queryset(self, **kwargs):
        params = {k: v for k, v in self.request.GET.items() if k != 'page'}

        if params.get('entity_type'):
            if params.get('entity_type') == 'person':
                return self._get_person_queryset(params)

            elif params.get('entity_type') == 'employer':
                return self._get_employer_queryset(params)

        else:
            matching_employers = self._get_employer_queryset(params)
            matching_people = self._get_person_queryset(params)

            return list(matching_employers) + list(matching_people)

    def _get_person_queryset(self, params):
        condition = Q()

        if params:
            if params.get('name'):
                name = Q(search_vector=params.get('name'))
                condition &= name

            if params.get('employer'):
                child_employer = Q(jobs__position__employer__slug=params.get('employer'))
                parent_employer = Q(jobs__position__employer__parent__slug=params.get('employer'))
                condition &= child_employer | parent_employer

        return Person.objects.filter(condition)\
                             .order_by('-jobs__salaries__amount')

    def _get_employer_queryset(self, params):
        condition = Q()

        employers = Employer.objects.all()

        if params:
            if params.get('name'):
                employers = employers.annotate(search_vector=SearchVector('name'))
                name = Q(search_vector=params.get('name'))
                condition &= name

            if params.get('employer'):
                name = Q(slug=params.get('employer'))
                condition &= name

            if params.get('parent'):
                parent = Q(parent__slug=params.get('parent'))
                condition &= parent

        return employers.filter(condition)\
                        .select_related('parent')\
                        .annotate(budget=Sum('position__job__salaries__amount'))\
                        .order_by('-budget')


def entity_lookup(request):
    q = request.GET['term']

    top_level = Q(parent_id__isnull=True)
    high_budget = Q(budget__gt=1000000)

    employers = Employer.objects\
                        .annotate(budget=Sum('position__job__salaries__amount'))\
                        .filter(top_level | high_budget)

    people = Person.objects.filter(jobs__salaries__amount__gt=100000)

    if q:
        employers = employers.filter(name__istartswith=q)[:10]

        last_token = q.split(' ')[-1]

        people = people.filter(
            Q(search_vector=q) | Q(last_name__istartswith=last_token)
        )[:10]

    entities = []

    for e in chain(employers, people):
        data = {
            'label': str(e),
            'value': str(e),
        }

        if isinstance(e, Person):
            url = '/person/{slug}'
            category = 'Person'

        else:
            url = '/employer/{slug}'
            category = 'Employer'

        data.update({
            'url': url.format(slug=e.slug),
            'category': category,
        })

        entities.append(data)

    return JsonResponse(entities, safe=False)
