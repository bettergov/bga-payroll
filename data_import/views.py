import datetime
import json

from django.http import HttpResponse, JsonResponse
from django.shortcuts import redirect
from django.urls import reverse
from django.views import View
from django.views.generic import DetailView, ListView
from django.views.generic.edit import FormView

from data_import.forms import UploadForm
from data_import.models import SourceFile, StandardizedFile, RespondingAgency, \
    Upload
from data_import.utils import ChildEmployerQueue, ParentEmployerQueue, \
    RespondingAgencyQueue

from payroll.models import Employer


class SourceFileHook(View):
    def post(self, request):
        '''
        Accept post containing file metadata & ID in Google Drive
        '''
        upload = Upload.objects.create()
        source_files = json.loads(request.POST['source_files'])

        for file_metadata in source_files:
            agency = file_metadata.pop('responding_agency')
            responding_agency, _ = RespondingAgency.objects.get_or_create(name=agency)

            file_metadata['upload'] = upload
            file_metadata['responding_agency'] = responding_agency

            file_metadata = self._hydrate_date_objects(file_metadata)

            SourceFile.objects.create(**file_metadata)

        # TO-DO: Kick off delayed task, which iterates over all source files
        # without an attached file and calls SourceFile.download_from_drive

        return HttpResponse('Caught!')

    def _hydrate_date_objects(self, file_metadata):
        '''
        Convert date strings to Python date objects.
        '''
        date_fields = [k for k in file_metadata.keys() if k.endswith('date')]

        for field in date_fields:
            date_string = file_metadata[field]
            date_object = datetime.datetime.strptime(date_string, '%Y-%m-%d')
            file_metadata[field] = date_object

        return file_metadata


class StandardizedDataUpload(FormView):
    template_name = 'data_import/upload.html'
    form_class = UploadForm
    success_url = 'upload-success/'

    def form_valid(self, form):
        upload = Upload.objects.create()

        uploaded_file = form.cleaned_data['standardized_file']
        now = datetime.datetime.now().strftime('%Y-%m-%dT%H%M%S')
        uploaded_file.name = '{}-{}'.format(now, uploaded_file.name)

        s_file_meta = {
            'standardized_file': uploaded_file,
            'upload': upload,
            'reporting_year': form.cleaned_data['reporting_year'],
        }

        s_file = StandardizedFile.objects.create(**s_file_meta)
        s_file.copy_to_database()

        return super().form_valid(form)


class Uploads(ListView):
    '''
    Index of data import. Display a list of standardized uploads,
    their statuses, and next steps.
    '''
    template_name = 'data_import/index.html'
    model = Upload
    context_object_name = 'uploads'
    paginate_by = 25

    def get_queryset(self):
        return Upload.objects.filter(standardized_file__isnull=False)\
                             .order_by('-created_at')


class Review(DetailView):
    template_name = 'data_import/review.html'

    def dispatch(self, request, *args, **kwargs):
        '''
        If there are no more items to review, flush the matched
        data to the raw_payroll table, and redirect to the index.

        Otherwise, show the review.
        '''
        if self.q.remaining > 0:
            return super().dispatch(request, *args, **kwargs)

        else:
            # TO-DO: Make sure this can't be triggered more than once.
            self.finish_review_step()
            return redirect(reverse('data-import'))

    def get_object(self):
        '''
        If there are no items for checkout, return to main page where
        the user will be told there is work remaining, but none is
        currently available.
        '''
        item_id, item = self.q.checkout()

        if item:
            item['id'] = item_id.decode('utf-8')
            return item

        else:
            return redirect(reverse('data-import', kwargs={'pending': True}))

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        context.update({
            'entity': self.entity,
            'entities': self.entities,
            's_file_id': self.kwargs['s_file_id'],
            'remaining': self.q.remaining,
        })

        return context

    def finish_review_step(self):
        s_file = StandardizedFile.objects.get(id=self.kwargs['s_file_id'])

        if not s_file.processing:
            getattr(s_file, self.transition)()


class RespondingAgencyReview(Review):
    transition = 'select_unseen_parent_employer'
    entity = 'responding agency'
    entities = 'responding agencies'

    @property
    def q(self):
        return RespondingAgencyQueue(self.kwargs['s_file_id'])


class ParentEmployerReview(Review):
    transition = 'select_unseen_child_employer'
    entity = 'parent employer'
    entities = 'parent employers'

    @property
    def q(self):
        return ParentEmployerQueue(self.kwargs['s_file_id'])


class ChildEmployerReview(Review):
    transition = 'select_invalid_salary'
    entity = 'child employer'
    entities = 'child employers'

    @property
    def q(self):
        return ChildEmployerQueue(self.kwargs['s_file_id'])


def review(request):
    '''
    Both /match/ and /add/ resolve here.
    '''
    data = json.loads(request.POST['data'])

    entity_type = data['entity_type']
    s_file_id = data['s_file_id']
    unseen = data['unseen']
    match = data.get('match')  # None if adding

    if 'match' in request.build_absolute_uri('?'):
        # If we're matching, assert a match came through
        assert match

    q_map = {
        'responding-agency': RespondingAgencyQueue,
        'parent-employer': ParentEmployerQueue,
        'child-employer': ChildEmployerQueue,
    }

    q_obj = q_map[entity_type]

    q = q_obj(s_file_id)

    q.match_or_create(unseen, match)

    return JsonResponse({'status_code': 200})


def review_entity_lookup(request, entity_type):
    q = request.GET['term']

    queryset_map = {
        'responding-agency': RespondingAgency.objects,
        'parent-employer': Employer.objects.filter(parent_id__isnull=True),
        'child-employer': Employer.objects.filter(parent_id__isnull=False),
    }

    queryset = queryset_map[entity_type]

    entities = []

    for e in queryset.filter(name__istartswith=q):
        data = {
            'label': str(e),
            'value': str(e),
        }
        entities.append(data)

    return JsonResponse(entities, safe=False)
