# -*- coding: utf-8 -*-
import calendar
import json

from django.utils import simplejson
from django.http import HttpResponse, Http404
from django.views.decorators.csrf import csrf_exempt
from django.views.generic import View
from django.contrib.contenttypes.models import ContentType
from django.core.urlresolvers import reverse
from django.utils.decorators import method_decorator

from pygnupgaddon import tools
from sadiki.core.models import Distribution, Requestion, Sadik, \
    EvidienceDocument, REQUESTION_IDENTITY, STATUS_DECISION, STATUS_DISTRIBUTED
from sadiki.api.utils import sign_is_valid, make_sign
from sadiki.operator.forms import ConfirmationForm
from sadiki.core.workflow import workflow
from sadiki.core.signals import post_status_change, pre_status_change


class SignJSONResponseMixin(object):
    def render_to_response(self, context):
        return self.get_json_response(self.convert_context_to_json(context))

    def get_json_response(self, content, **kwargs):
        return HttpResponse(content, mimetype='application/json; charset=utf-8',
                            **kwargs)

    def convert_context_to_json(self, context):
        result = tools.get_signed_json(context)
        return simplejson.dumps(result, ensure_ascii=False)


class ChangeRequestionStatus(View, SignJSONResponseMixin):
    """
    Реализация метода создания заявки на проверку документов.
    """
    form = ConfirmationForm

    @method_decorator(csrf_exempt)
    def dispatch(self, request, *args, **kwargs):
        return super(ChangeRequestionStatus, self).dispatch(
            request, *args, **kwargs)

    def post(self, request):
        data = json.loads(request.body)
        requestion = Requestion.objects.get(pk=data['requestion_id'])
        transition_indexes = workflow.available_transitions(
            src=requestion.status, dst=int(data['dst_status']))
        # TODO: Проверка на корректность ДОУ?
        # sadik = requestion.distributed_in_vacancy.sadik_group.sadik
        if transition_indexes:
            transition = workflow.get_transition_by_index(transition_indexes[0])
            form = self.form(requestion=requestion,
                             data={'reason': u"Решение оператора ЭС",
                                   'transition': transition.index,
                                   'confirm': "yes"},
                             initial={'transition': transition.index})
            if form.is_valid():
                pre_status_change.send(
                    sender=Requestion, request=request, requestion=requestion,
                    transition=transition, form=form)
                requestion.status = transition.dst
                requestion.save()
                post_status_change.send(
                    sender=Requestion, request=request, requestion=requestion,
                    transition=transition, form=form)
            else:
                print form.errors
        # TODO: Обработка ошибок
        return self.render_to_response(data)


def get_distributions(request):
    data = Distribution.objects.all().values_list('id', flat=True)
    return HttpResponse(simplejson.dumps(list(data)), mimetype='text/json')


@csrf_exempt
def get_distribution(request):
    if request.method == 'GET':
        raise Http404
    signed_data = request.POST.get('signed_data')
    if not (signed_data and sign_is_valid(signed_data)):
        raise Http404
    _id = request.POST.get('id')
    if not _id:
        raise Http404
    distribution_qs = Distribution.objects.filter(pk=_id)
    if len(distribution_qs) != 1:
        return HttpResponse(simplejson.dumps([0, ]), mimetype='text/json')
    dist = distribution_qs[0]
    results = []
    sadiks_ids = Requestion.objects.filter(
        distributed_in_vacancy__distribution=dist).distinct().values_list(
            'distributed_in_vacancy__sadik_group__sadik', flat=True)
    for sadik in Sadik.objects.filter(
            id__in=sadiks_ids).distinct().order_by('number'):
        requestions = Requestion.objects.filter(
            distributed_in_vacancy__distribution=dist,
            distributed_in_vacancy__sadik_group__sadik=sadik,
            status__in=[STATUS_DECISION, STATUS_DISTRIBUTED]).order_by(
                '-birth_date').select_related('profile').select_related(
                    'distributed_in_vacancy__sadik_group__age_group')
        requestion_ct = ContentType.objects.get_for_model(Requestion)
        if requestions:
            kg_dict = {'kindergtn': sadik.id, 'requestions': []}
            for requestion in requestions:
                birth_cert = EvidienceDocument.objects.filter(
                    template__destination=REQUESTION_IDENTITY,
                    content_type=requestion_ct, object_id=requestion.id)[0]
                url = request.build_absolute_uri(reverse(
                    'requestion_logs', args=(requestion.id, )))
                kg_dict['requestions'].append({
                    'requestion_number': requestion.requestion_number,
                    'name': requestion.name,
                    'status': requestion.status,
                    'queue_profile_url': url,
                    'birth_date': calendar.timegm(
                        requestion.birth_date.timetuple()),
                    'birth_cert': birth_cert.document_number})

            results.append(kg_dict)
    data = [{
        'id': dist.id,
        'start': calendar.timegm(dist.init_datetime.timetuple()),
        'end': calendar.timegm(dist.end_datetime.timetuple()),
        'year': dist.year.year,
        'results': results,
    }]
    response = [{'sign': make_sign(data).data, 'data': data}]
    return HttpResponse(simplejson.dumps(response), mimetype='text/json')


@csrf_exempt
def get_child(request):
    if request.method == 'GET':
        raise Http404
    doc = request.POST.get('doc')
    signed_data = request.POST.get('sign')
    if sign_is_valid(signed_data):
        requestion_ct = ContentType.objects.get_for_model(Requestion)
        requestion_ids = EvidienceDocument.objects.filter(
            content_type=requestion_ct, document_number=doc,
            template__destination=REQUESTION_IDENTITY).values_list('object_id',
                                                                   flat=True)
        if not requestion_ids:
            return HttpResponse()
        requestions = Requestion.objects.filter(id__in=requestion_ids)
        data = []
        for requestion in requestions:
            url = request.build_absolute_uri(reverse('requestion_logs',
                                                     args=(requestion.id, )))
            req_dict = {
                'requestion_number': requestion.requestion_number,
                'status': requestion.status,
                'id': requestion.id,
                'url': url,
            }
            if requestion.distribution_datetime:
                req_dict['distribution_datetime'] = calendar.timegm(
                    requestion.distribution_datetime.timetuple())
            data.append(req_dict)
        response = [{'sign': make_sign(data).data, 'data': data}]
        return HttpResponse(simplejson.dumps(response), mimetype='text/json')
    raise Http404


@csrf_exempt
def api_test(request):
    status = 'error'
    msg = None
    if request.method == 'GET':
        msg = "Wrong method, use POST instead of GET"
    signed_data = request.POST.get('signed_data')
    if not (signed_data and sign_is_valid(signed_data)):
        msg = "Sing check error"
    test_string = request.POST.get('test_string')
    if not test_string == u"Проверочная строка":
        msg = "wrong test_string"
    if not msg:
        status = 'ok'
        msg = "All passed"
    response = [{'sign': make_sign(msg).data, 'data': msg, 'status': status}]
    return HttpResponse(simplejson.dumps(response), mimetype='text/json')


@csrf_exempt
def get_kindergartens(request):
    data = []
    for sadik in Sadik.objects.all():
        data.append({
            'id': sadik.id,
            'address': sadik.address.text,
            'phone': sadik.phone,
            'name': sadik.short_name,
            'head_name': sadik.head_name,
            'email': sadik.email,
            'site': sadik.site,
        })
    response = [{'sign': make_sign(data).data, 'data': data}]
    return HttpResponse(simplejson.dumps(response), mimetype='text/json')
