# -*- coding: utf-8 -*-
from django.conf import settings
from django.contrib import messages
from django.contrib.contenttypes.generic import generic_inlineformset_factory
from django.core.urlresolvers import reverse
from django.http import HttpResponseRedirect
from django.shortcuts import get_object_or_404
from django.views.generic.base import TemplateView
from django.utils import simplejson
from sadiki.account.forms import RequestionForm, \
    ChangeRequestionForm, PreferredSadikForm, BenefitsForm, DocumentForm, BenefitCategoryForm, ChangeRequestionBaseForm, PreferredSadikWithAreasNameForm
from sadiki.core.models import Profile, Requestion, \
    BENEFIT_DOCUMENT, STATUS_REQUESTER_NOT_CONFIRMED, \
    EvidienceDocument, STATUS_REQUESTER, BenefitCategory, AgeGroup, STATUS_DISTRIBUTED, STATUS_NOT_APPEAR, STATUS_NOT_APPEAR_EXPIRE, Sadik
from sadiki.core.permissions import RequirePermissionsMixin
from sadiki.core.utils import get_openlayers_js, get_current_distribution_year
from sadiki.core.workflow import ADD_REQUESTION, CHANGE_PROFILE, \
    CHANGE_REQUESTION, CHANGE_PREFERRED_SADIKS, CHANGE_BENEFITS, CHANGE_DOCUMENTS
from sadiki.logger.models import Logger
from sadiki.core.views_base import GenerateBlankBase


class AccountPermissionMixin(RequirePermissionsMixin):
    u"""
    проверка является ли пользователь оператором
    """
    required_permissions = ['is_requester']


class AccountRequestionMixin(AccountPermissionMixin):

    def check_permissions(self, request, requestion):
        if AccountPermissionMixin.check_permissions(self, request):
            return requestion.profile.user == request.user
        return False

    def dispatch(self, request, requestion_id):
        requestion = get_object_or_404(Requestion, id=requestion_id)
        return RequirePermissionsMixin.dispatch(self, request,
            requestion=requestion)


class AccountRequestionEditMixin(AccountRequestionMixin):
    def check_permissions(self, request, requestion):
        return super(AccountRequestionEditMixin, self).check_permissions(
            request, requestion) and requestion.editable


class AccountFrontPage(AccountPermissionMixin, TemplateView):
    u"""
    отображается страница личного кабинета пользователя
    """
    template_name = 'account/frontpage.html'

    def get_context_data(self, **kwargs):
        context = {
            'params': kwargs,
            'profile': self.request.user.profile,
        }
        vkontakte_associations = self.request.user.social_auth.filter(provider='vkontakte-oauth2')
        if vkontakte_associations:
            context.update({'vkontakte_association': vkontakte_associations[0]})
        return context


class RequestionAdd(AccountPermissionMixin, TemplateView):
    u"""Добавление заявки пользователем"""
    template_name = 'account/requestion_add.html'

    def get_context_data(self, **kwargs):
        return {
            'params': kwargs,
        }

    def get(self, request, *args, **kwargs):
        context = self.get_context_data()
        form = RequestionForm()
        if settings.FACILITY_STORE == settings.FACILITY_STORE_YES:
            benefits_form = BenefitsForm()
        else:
            benefits_form = BenefitCategoryForm()
        context.update({'form': form, 'benefits_form': benefits_form,
            'openlayers_js': get_openlayers_js()})
        return self.render_to_response(context)

    def post(self, request, *args, **kwargs):
        context = self.get_context_data()
        form = RequestionForm(request.POST)
        if settings.FACILITY_STORE == settings.FACILITY_STORE_YES:
            benefits_form = BenefitsForm(data=request.POST)
        else:
            benefits_form = BenefitCategoryForm(data=request.POST)
        if (form.is_valid() and benefits_form.is_valid()):
            profile = request.user.get_profile()
            requestion = form.save(profile=profile)
            pref_sadiks = form.cleaned_data.get('pref_sadiks')
            benefits_form.instance = requestion
            requestion = benefits_form.save()
            context_dict = {'requestion': requestion,
                'pref_sadiks': pref_sadiks,
                'areas': form.cleaned_data.get('areas')}
            context_dict.update(dict([(field, benefits_form.cleaned_data[field])
                for field in benefits_form.changed_data]))
            Logger.objects.create_for_action(ADD_REQUESTION,
                context_dict=context_dict, extra={
                'user': request.user, 'obj': requestion,
                'added_pref_sadiks': pref_sadiks})
            messages.info(request, u'Добавлена заявка %s' % requestion.requestion_number)
            return HttpResponseRedirect(
                reverse('account_requestion_info',
                         kwargs={'requestion_id': requestion.id}))
        else:
            context.update({'form': form, 'benefits_form': benefits_form,
                'openlayers_js': get_openlayers_js()})
            return self.render_to_response(context)


class RequestionInfo(AccountRequestionMixin, TemplateView):
    template_name = 'account/requestion_info.html'

    def get(self, request, requestion):
        context = self.get_context_data(requestion)
        change_requestion_form = ChangeRequestionBaseForm(instance=requestion)
        change_benefits_form = BenefitsForm(instance=requestion)
        pref_sadiks_form = PreferredSadikWithAreasNameForm(instance=requestion)
        context.update({
            'change_requestion_form': change_requestion_form,
            'change_benefits_form': change_benefits_form,
            'pref_sadiks_form': pref_sadiks_form,
        })
        return self.render_to_response(context)

    def post(self, request, requestion):
        context = self.get_context_data(requestion)
        change_requestion_form = ChangeRequestionBaseForm(request.POST, instance=requestion)
        change_benefits_form = BenefitsForm(request.POST, instance=requestion)
        pref_sadiks_form = PreferredSadikWithAreasNameForm(request.POST, instance=requestion)
        if not requestion.editable:
            messages.error(request, u'Заявка %s не может быть изменена' % requestion)
            return HttpResponseRedirect(reverse('account_requestion_info', args=[requestion.id]))
        if all((change_requestion_form.is_valid(), change_benefits_form.is_valid(), pref_sadiks_form.is_valid())):
            if change_requestion_form.has_changed():
                change_requestion_form.save()
                context_dict = {'changed_fields': change_requestion_form.changed_data,
                    'requestion': requestion, 'areas': requestion.areas.all()}
                Logger.objects.create_for_action(CHANGE_REQUESTION,
                    context_dict=context_dict,
                    extra={'user': request.user, 'obj': requestion})
            # изменение льгот возможно только для документально неподтврежденных
            if requestion.status == STATUS_REQUESTER_NOT_CONFIRMED:
                if change_benefits_form.has_changed():
                    change_benefits_form.save()
                    context_dict = dict([(field, change_benefits_form.cleaned_data[field])
                        for field in change_benefits_form.changed_data])
                    context_dict.update({"requestion": requestion})
                    Logger.objects.create_for_action(CHANGE_BENEFITS,
                        context_dict=context_dict,
                        extra={'user': request.user, 'obj': requestion})
            if pref_sadiks_form.has_changed():
                pref_sadiks = set(requestion.pref_sadiks.all())
                pref_sadiks_form.save()
                new_pref_sadiks = set(requestion.pref_sadiks.all())
                added_pref_sadiks = new_pref_sadiks - pref_sadiks
                removed_pref_sadiks = pref_sadiks - new_pref_sadiks
                context_dict = {
                    'changed_data': pref_sadiks_form.changed_data,
                    'cleaned_data': pref_sadiks_form.cleaned_data,}
                Logger.objects.create_for_action(CHANGE_PREFERRED_SADIKS,
                    context_dict=context_dict,
                    extra={'user': request.user, 'obj': requestion,
                        'added_pref_sadiks': added_pref_sadiks,
                        'removed_pref_sadiks': removed_pref_sadiks})
            messages.success(request, u'Изменения в заявке %s сохранены' % requestion)
            return HttpResponseRedirect(reverse('account_requestion_info', kwargs={'requestion_id': requestion.id}))
        context.update({
            'change_requestion_form': change_requestion_form,
            'change_benefits_form': change_benefits_form,
            'pref_sadiks_form': pref_sadiks_form,
        })
        return self.render_to_response(context)

    def get_context_data(self, requestion, **kwargs):
        before = Requestion.objects.queue().requestions_before(requestion)
        benefits_before = before.benefits().count()
        confirmed_before = before.confirmed().count()
        requestions_before = before.count()
        benefits_after = Requestion.objects.queue().benefits().count() - benefits_before
        confirmed_after = Requestion.objects.queue().confirmed().count() - confirmed_before
        requestions_after = Requestion.objects.queue().count() - requestions_before
        offset = max(0, requestions_before - 20)
        queue_chunk = Requestion.objects.queue().add_distributed_sadiks()[offset:requestions_before + 20]

        # Вычесть свою заявку
        requestions_after -= 1
        if requestion.benefit_category.priority > 0:
            benefits_after -= 1
        if requestion.status == STATUS_REQUESTER:
            confirmed_after -= 1

        # для заявок вычисляем возрастные группы
        age_groups = AgeGroup.objects.all()
        current_distribution_year = get_current_distribution_year()
        for req in queue_chunk:
            req.age_groups_calculated = req.age_groups(
                age_groups=age_groups,
                current_distribution_year=current_distribution_year)
        pref_sadiks_ids = requestion.pref_sadiks.all().values_list('id', flat=True)
        sadiks_location_data = {}
        for sadik in Sadik.objects.all():
            if sadik.address.coords:
                sadiks_location_data.update({sadik.id: {
                    'id': sadik.id,
                    'location': sadik.address.coords.tuple,
                    'address': sadik.address.text,
                    'phone': sadik.phone,
                    'name': sadik.short_name,
                    'number': sadik.number,
                    'url': reverse('sadik_info', args=[sadik.id, ]),
                }})

        context = {
            'requestion': requestion,
            'benefits_before': benefits_before,
            'benefits_after': benefits_after,
            'confirmed_before': confirmed_before,
            'confirmed_after': confirmed_after,
            'requestions_before': requestions_before,
            'requestions_after': requestions_after,
            'queue': queue_chunk,
            'offset': offset,
            'NOT_APPEAR_STATUSES': [STATUS_NOT_APPEAR, STATUS_NOT_APPEAR_EXPIRE],
            'STATUS_DISTIRIBUTED': STATUS_DISTRIBUTED,
            'STATUS_REQUESTER_NOT_CONFIRMED': STATUS_REQUESTER_NOT_CONFIRMED,
            'sadiks_location_data': simplejson.dumps(sadiks_location_data),
            'pref_sadiks_ids': pref_sadiks_ids,
        }

        context.update(kwargs)
        return context


class RequestionChange(AccountRequestionEditMixin, TemplateView):
    u"""Изменение заявки пользователем"""
    template_name = 'account/requestion_change.html'
    queryset = Requestion.objects.all()

    def get(self, request, requestion):
        form = ChangeRequestionForm(instance=requestion)
        return self.render_to_response({'requestion': requestion,
            'form': form, 'openlayers_js': get_openlayers_js()})

    def post(self, request, requestion):
        form = ChangeRequestionForm(instance=requestion,
            data=request.POST)
        if form.is_valid():
            if form.has_changed():
                requestion = form.save()
#                write logs
                context_dict = {'changed_fields': form.changed_data,
                    'requestion': requestion}
                Logger.objects.create_for_action(CHANGE_REQUESTION,
                    context_dict=context_dict,
                    extra={'user': request.user, 'obj': requestion})
                messages.success(request, u'Изменения в заявке %s сохранены' % requestion)
            else:
                messages.info(request, u'Заявка %s не была изменена' % requestion)
            return HttpResponseRedirect(
                reverse('account_requestion_info',
                        kwargs={'requestion_id': requestion.id}))
        else:
            return self.render_to_response(
                {'form': form, 'requestion': requestion, 'openlayers_js': get_openlayers_js()})


class BenefitsChange(AccountRequestionEditMixin, TemplateView):
    u"""Изменение льгот и документов для льгот"""
    template_name = 'account/requestion_benefits_change.html'

    def check_permissions(self, request, requestion):
        return (super(BenefitsChange, self).check_permissions(request, requestion) and
            requestion.status == STATUS_REQUESTER_NOT_CONFIRMED)

    def get_own_documents(self, requestion):
        serialized = []
        for obj in requestion.evidience_documents():
            serialized.append({
                'id': obj.id,
                'template': obj.template_id,
                'confirmed': obj.confirmed,
                'document_number': obj.document_number,
            })
        return simplejson.dumps(serialized)

    def get(self, request, requestion):
        benefits_form = BenefitsForm(instance=requestion)
        context = {
            'requestion': requestion,
            'benefits_form': benefits_form,
            'documents': self.get_own_documents(requestion),
            }
        return self.render_to_response(context)

    def post(self, request, requestion):
        benefits_form = BenefitsForm(
            data=request.POST,
            instance=requestion)
        if benefits_form.is_valid():
            benefits_form.save()
            context_dict = dict([(field, benefits_form.cleaned_data[field])
                for field in benefits_form.changed_data])
            context_dict.update({"requestion": requestion})
            Logger.objects.create_for_action(CHANGE_BENEFITS,
                context_dict=context_dict,
                extra={'user': request.user, 'obj': requestion})
            messages.success(request, u'Льготы для заявки %s были изменены' %
                requestion.requestion_number)
            return HttpResponseRedirect(
                reverse('account_requestion_info',
                    kwargs={'requestion_id': requestion.id}))
        else:
            return self.render_to_response({
                'requestion': requestion,
                'benefits_form': benefits_form,
                'documents': self.get_own_documents(requestion),
            })


class BenefitCategoryChange(AccountRequestionEditMixin, TemplateView):
    template_name = 'account/requestion_benefitcategory_change.html'

    def check_permissions(self, request, requestion):
        return (super(BenefitCategoryChange, self).check_permissions(request, requestion) and
            requestion.status == STATUS_REQUESTER_NOT_CONFIRMED)

    def get(self, request, requestion):
        from sadiki.account.forms import BenefitCategoryForm
        form = BenefitCategoryForm(instance=requestion)
        return self.render_to_response(
            {'requestion': requestion, 'form': form})

    def post(self, request, requestion):
        from sadiki.account.forms import BenefitCategoryForm
        form = BenefitCategoryForm(instance=requestion, data=request.POST)
        if form.is_valid():
            if form.has_changed():
                form.save()
                context_dict = {"requestion": requestion}
                Logger.objects.create_for_action(CHANGE_BENEFITS,
                    context_dict=context_dict,
                    extra={'user': request.user, 'obj': requestion})
                messages.success(
                    request, u'''Льготы для заявки %s были изменены
                         ''' % requestion.requestion_number)
            else:
                messages.success(
                    request, u'''Льготы для заявки %s не были изменены
                         ''' % requestion.requestion_number)
            return HttpResponseRedirect(
                    reverse('account_requestion_info',
                            kwargs={'requestion_id': requestion.id}))
        else:
            return self.render_to_response(
                {'requestion': requestion, 'form': form})


class PreferredSadiksChange(AccountRequestionEditMixin, TemplateView):
    u"""Изменение приоритетных ДОУ"""
    template_name = 'account/requestion_preferredsadiks_change.html'

    def get(self, request, requestion):
        form = PreferredSadikForm(instance=requestion)
        return self.render_to_response({
            'requestion': requestion,
            'form': form,
        })

    def post(self, request, requestion):
        form = PreferredSadikForm(instance=requestion, data=request.POST)
        if form.is_valid():
            if form.has_changed():
                # TODO: Добавить изящества в составление контекста для логов
                pref_sadiks = set(requestion.pref_sadiks.all())
                requestion = form.save()
                new_pref_sadiks = set(requestion.pref_sadiks.all())
                added_pref_sadiks = new_pref_sadiks - pref_sadiks
                removed_pref_sadiks = pref_sadiks - new_pref_sadiks
                context_dict = {
                    'changed_data': form.changed_data,
                    'pref_sadiks': requestion.pref_sadiks.all(),
                    'distribute_in_any_sadik': requestion.distribute_in_any_sadik}
                Logger.objects.create_for_action(CHANGE_PREFERRED_SADIKS,
                    context_dict=context_dict,
                    extra={'user': request.user, 'obj': requestion,
                        'added_pref_sadiks': added_pref_sadiks,
                        'removed_pref_sadiks': removed_pref_sadiks})
                messages.info(request, u'''
                     Приоритетные ДОУ для заявки %s изменены
                     ''' % requestion.requestion_number)
            else:
                messages.info(request, u'''Приоритетные ДОУ не были изменены''')
            return HttpResponseRedirect(
                reverse('account_requestion_info',
                        kwargs={'requestion_id': requestion.id}))
        return self.render_to_response({
            'requestion': requestion,
            'form': form,
        })


class DocumentsChange(AccountRequestionMixin, TemplateView):
    u"""Управление документами"""
    template_name = 'account/requestion_documents_change.html'

    def check_permissions(self, request, requestion):
        return (super(DocumentsChange, self).check_permissions(request, requestion) and
            requestion.status == STATUS_REQUESTER_NOT_CONFIRMED)

    def get(self, request, requestion):
        DocumentFormset = generic_inlineformset_factory(EvidienceDocument,
            form=DocumentForm, exclude=['confirmed', ], extra=1)
#        нужны только документы для льгот
        formset = DocumentFormset(
            instance=requestion, queryset=EvidienceDocument.objects.filter(
            template__destination=BENEFIT_DOCUMENT))
        return self.render_to_response({
            'formset': formset,
            'requestion': requestion,
            'confirmed': EvidienceDocument.objects.documents_for_object(
                requestion).confirmed(),
        })

    def post(self, request, requestion):
        DocumentFormset = generic_inlineformset_factory(EvidienceDocument,
            form=DocumentForm, exclude=['confirmed', ], extra=1)

        formset = DocumentFormset(request.POST,
            instance=requestion, queryset=EvidienceDocument.objects.filter(
            template__destination=BENEFIT_DOCUMENT))

        if formset.is_valid():
            if formset.has_changed():
                formset.save()
                messages.info(request, u'''Документы были изменены''')
                Logger.objects.create_for_action(
                        CHANGE_DOCUMENTS,
                        context_dict={'benefit_documents': requestion.evidience_documents().filter(
                            template__destination=BENEFIT_DOCUMENT)},
                        extra={'user': request.user, 'obj': requestion})
            else:
                messages.info(request, u'''Документы не были изменены''')
            return HttpResponseRedirect(reverse('account_requestion_info',
                    kwargs={'requestion_id': requestion.id}))
        else:
            return self.render_to_response({
                'formset': formset,
                'requestion': requestion,
                'confirmed': requestion.evidience_documents().confirmed(),
            })


class GenerateBlank(AccountRequestionMixin, GenerateBlankBase):
    pass
