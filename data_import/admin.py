import datetime

from django.contrib import admin

from data_import.models import SourceFile, Upload, RespondingAgency


class AdminRespondingAgency(admin.ModelAdmin):
    search_fields = ('name',)
    fields = ('name',)
    ordering = ('name',)

    def get_model_perms(self, request):
        '''
        A hack to hide the standalone RespondingAgency from the admin.
        '''
        return {}

    def get_search_results(self, request, queryset, search_term):
        '''
        Only show responding agencies without a source file.
        '''
        queryset, use_distinct = super().get_search_results(request, queryset, search_term)
        queryset = queryset.exclude(source_files__reporting_year=2017)
        return queryset, use_distinct


class AdminSourceFile(admin.ModelAdmin):
    model = SourceFile

    fields = (
        'source_file',
        'responding_agency',
        'reporting_year',
        'reporting_period_start_date',
        'reporting_period_end_date',
    )

    autocomplete_fields = ['responding_agency']

    search_fields = ('responding_agency__name', 'reporting_year',)

    def get_readonly_fields(self, request, obj=None):
        '''
        Disable editing of responding agency for existing source files.
        '''
        if obj:
            return ['responding_agency']
        else:
            return []

    def save_model(self, request, obj, form, change):
        obj.upload = Upload.objects.create(created_by=request.user)

        # Auto-fill reporting period dates, if they were not provided
        if not obj.reporting_period_start_date:
            obj.reporting_period_start_date = datetime.datetime(obj.reporting_year, 1, 1)

        if not obj.reporting_period_end_date:
            obj.reporting_period_end_date = datetime.datetime(obj.reporting_year, 12, 31)

        super().save_model(request, obj, form, change)


admin.site.register(SourceFile, AdminSourceFile)
admin.site.register(RespondingAgency, AdminRespondingAgency)
