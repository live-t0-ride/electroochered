# -*- coding: utf-8 -*-
import json
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.models import Permission, User
from django.contrib.contenttypes.generic import generic_inlineformset_factory
from django.core.urlresolvers import reverse
from django.http import HttpResponseRedirect, HttpResponseBadRequest, HttpResponse, Http404
from django.shortcuts import get_object_or_404
from django.template import TemplateDoesNotExist, loader
from django.template.response import TemplateResponse
from django.utils.http import urlquote
from django.views.generic import TemplateView, View
from sadiki.account.forms import BenefitsForm, \
    ChangeRequestionForm, PreferredSadikForm, DocumentForm, BenefitCategoryForm
from sadiki.account.views import BenefitsChange as AnonyBenefitsChange, \
    SocialProfilePublic as AccountSocialProfilePublic, \
    RequestionAdd as AccountRequestionAdd, \
    BenefitCategoryChange as AnonymBenefitCategoryChange, \
    RequestionInfo as AccountRequestionInfo,\
    RequestionChange as AnonymRequestionChange, \
    PreferredSadiksChange as AnonymPreferredSadiksChange, \
    DocumentsChange as AnonymDocumentsChange, get_json_sadiks_location_data, AccountFrontPage
from sadiki.anonym.views import Queue as AnonymQueue, \
    RequestionSearch as AnonymRequestionSearch
from sadiki.authorisation.models import VerificationKey
from sadiki.core.models import STATUS_REQUESTER, STATUS_REQUESTER_NOT_CONFIRMED, \
    STATUS_DISTRIBUTED, Requestion, EvidienceDocument, BENEFIT_DOCUMENT, \
    REQUESTION_IDENTITY, BenefitCategory, Profile, REQUESTION_TYPE_IMPORTED, STATUS_ON_DISTRIBUTION
from sadiki.core.permissions import RequirePermissionsMixin, \
    REQUESTER_PERMISSION
from sadiki.core.signals import post_status_change, pre_status_change
from sadiki.core.utils import check_url, get_openlayers_js, get_user_by_email, get_unique_username
from sadiki.core.workflow import REQUESTION_REGISTRATION, \
    CHANGE_PROFILE_BY_OPERATOR, CHANGE_BENEFITS, CHANGE_REQUESTION_BY_OPERATOR, \
    CHANGE_PREFERRED_SADIKS_BY_OPERATOR, Transition, workflow, CREATE_PROFILE, CHANGE_DOCUMENTS_BY_OPERATOR, CHANGE_REQUESTION_LOCATION
from sadiki.logger.models import Logger
from sadiki.operator.forms import OperatorRequestionForm, OperatorSearchForm, \
    DocumentGenericInlineFormSet, RequestionIdentityDocumentForm, EmailForm, \
    ProfileSearchForm, BaseConfirmationForm, HiddenConfirmation, ChangeLocationForm
from sadiki.operator.views.base import OperatorPermissionMixin, \
    OperatorRequestionMixin, OperatorRequestionEditMixin, \
    OperatorRequestionCheckIdentityMixin
from django.forms.models import ModelFormMetaclass
from sadiki.core.views_base import GenerateBlankBase, generate_pdf
from sadiki.operator.forms import ConfirmationForm


class FrontPage(OperatorPermissionMixin, TemplateView):
    u"""
    отображается страница рабочего места оператора
    """
    template_name = 'operator/frontpage.html'


class Queue(OperatorPermissionMixin, AnonymQueue):
    u"""Отображение очереди в район для оператора"""
    template_name = 'operator/queue.html'


class Registration(OperatorPermissionMixin, TemplateView):
    u"""
    одновременная регистрация пользователя и заявки для оператора
    """
    template_name = 'operator/registration.html'

    def dispatch(self, request, profile_id=None):
        if profile_id:
            profile = get_object_or_404(Profile, id=profile_id)
            if not profile.user.is_requester():
                raise Http404
        else:
            profile = None
        return super(Registration, self).dispatch(request, profile)

    def create_profile(self):
        user = User.objects.create_user(username=get_unique_username())
        #        задаем права
        permission = Permission.objects.get(codename=u'is_requester')
        user.user_permissions.add(permission)
        user.set_username_by_id()
        user.save()
        return Profile.objects.create(user=user)

    def get(self, request, profile):
        requestion_form = OperatorRequestionForm()
        if settings.FACILITY_STORE == settings.FACILITY_STORE_YES:
            benefits_form = BenefitsForm()
        else:
            benefits_form = BenefitCategoryForm()
        context = {'form': requestion_form,
            'benefits_form': benefits_form,
            'openlayers_js': get_openlayers_js(),
            'sadiks_location_data': get_json_sadiks_location_data(),
            'profile': profile}
        return self.render_to_response(context)

    def post(self, request, profile):
        requestion_form = OperatorRequestionForm(request.POST,)
        if settings.FACILITY_STORE == settings.FACILITY_STORE_YES:
            benefits_form = BenefitsForm(data=request.POST)
        else:
            benefits_form = BenefitCategoryForm(data=request.POST)
        if requestion_form.is_valid() and benefits_form.is_valid():
            if not profile:
                profile = self.create_profile()
            requestion = requestion_form.save(profile=profile)
            benefits_form.instance = requestion
            requestion = benefits_form.save()
            added_pref_sadiks = requestion_form.cleaned_data.get('pref_sadiks')
            context_dict = {'requestion': requestion,
                          'pref_sadiks': requestion.pref_sadiks.all(),
                          'areas': requestion_form.cleaned_data.get('areas')}
            context_dict.update(dict([(field, benefits_form.cleaned_data[field])
                for field in benefits_form.changed_data]))
            Logger.objects.create_for_action(CREATE_PROFILE,
                context_dict={'user': profile.user, 'profile': profile},
                extra={'user': request.user, 'obj': profile})
            Logger.objects.create_for_action(REQUESTION_REGISTRATION,
                context_dict=context_dict,
                extra={'user': request.user, 'obj': requestion,
                    'added_pref_sadiks': added_pref_sadiks, })
            messages.info(request,
                u'Регистрация пользователя прошла успешно. Создана заявка %s' %
                requestion.requestion_number)
#            если были заданы типы льгот, то редирект на изменение документов
            if (settings.FACILITY_STORE == settings.FACILITY_STORE_YES and
                requestion.benefit_category != BenefitCategory.objects.category_without_benefits()):
                return HttpResponseRedirect(reverse("operator_benefits_change", kwargs={'requestion_id': requestion.id}))
#            иначе на страницу с информацией о заявке
            return HttpResponseRedirect(
                reverse('operator_requestion_info',
                    kwargs={'requestion_id': requestion.id}))


        context = {'form': requestion_form,
            'benefits_form': benefits_form,
            'openlayers_js': get_openlayers_js(),
            'sadiks_location_data': get_json_sadiks_location_data(),
            'profile': profile}
        return self.render_to_response(context)


class RequestionAdd(OperatorPermissionMixin, AccountRequestionAdd):
    template_name = "operator/requestion_add.html"
    requestion_form = OperatorRequestionForm

    def redirect_to(self, requestion):
        return reverse('operator_requestion_info', kwargs={'requestion_id': requestion.id})

    def dispatch(self, request, profile_id):
        profile = get_object_or_404(Profile, id=profile_id)
        return super(AccountRequestionAdd, self).dispatch(request, profile=profile)


class RequestionSearch(OperatorPermissionMixin, AnonymRequestionSearch):
    u"""
    поиск заявок для оператора
    """
    template_name = 'operator/requestion_search.html'
    form = OperatorSearchForm
    initial_query = Requestion.objects.all()
    field_weights = {
        'requestion_number__exact': 0,
        'birth_date__exact': 6,
        'registration_datetime__range': 2,
        'number_in_old_list__exact': 1,
        'id__in': 5,
        'name__icontains': 3,
        }

    def guess_more(self, initial_query):
        u"""
        попробуем угадать, какой запрос принесет больше успеха,
        в случае если не найдено ни одной заявки.
        Убираем самый легковесный параметр
        """
        # необходимо минимум
        if len(initial_query) >= 2:
            new_query = initial_query.copy()
            for _ in initial_query.keys():
                lightest_key = min(new_query.keys(), key=lambda x: self.field_weights[x])
                del new_query[lightest_key]
                more_results = Requestion.objects.queue().filter(**new_query)
                if more_results:
                    return new_query, more_results


class ProfileInfo(OperatorPermissionMixin, AccountFrontPage):
    template_name = "operator/profile_info.html"

    def dispatch(self, request, profile_id):
        profile = get_object_or_404(Profile, id=profile_id)
        return super(AccountFrontPage, self).dispatch(request, profile=profile)

    def get_context_data(self, **kwargs):
        context = super(ProfileInfo, self).get_context_data(**kwargs)
        context.update(
            {'reset_password_form': HiddenConfirmation(initial={'action': 'reset_password'})})
        return context


class RequestionInfo(OperatorRequestionMixin, AccountRequestionInfo):
    template_name = "operator/requestion_info.html"

    def redirect_to(self, requestion):
        return reverse('operator_requestion_info', kwargs={'requestion_id': requestion.id})

    def get_queue_data(self, requestion):
        return {}

    def can_change_benefits(self, requestion):
        return requestion.editable


class RequestionChange(OperatorRequestionCheckIdentityMixin,
    OperatorRequestionEditMixin, AnonymRequestionChange):
    u"""
    изменение заявки оператором
    """
    template_name = 'operator/requestion_change.html'

#    изменил запись логов и редирект
    def post(self, request, requestion):
        form = ChangeRequestionForm(instance=requestion,
            data=request.POST)
        if form.is_valid():
            if form.has_changed():
                requestion = form.save()
#                write logs
                context_dict = {'changed_fields': form.changed_data,
                    'requestion': requestion}
                Logger.objects.create_for_action(CHANGE_REQUESTION_BY_OPERATOR,
                    context_dict=context_dict,
                    extra={'user': request.user, 'obj': requestion})
                messages.success(request, u'Изменения в заявке %s сохранены' % requestion)
            else:
                messages.info(request, u'Заявка %s не была изменена' % requestion)
            return HttpResponseRedirect(
                reverse('operator_requestion_info',
                        kwargs={'requestion_id': requestion.id}))
        else:
            return self.render_to_response(
                {'form': form, 'requestion': requestion,
                 'openlayers_js': get_openlayers_js()})


class BenefitsChange(OperatorRequestionCheckIdentityMixin,
    OperatorRequestionEditMixin, AnonyBenefitsChange):
    u"""
    изменение льгот оператором
    """
    template_name = 'operator/requestion_benefits_change.html'

    def post(self, request, requestion):
        u"""
        метод скопирован из родительского BenefitsChange,
        но после успешного сохранения другой редирект.
        Также предполагается другая запись логов
        """
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
                reverse('operator_requestion_info',
                    kwargs={'requestion_id': requestion.id}))
        else:
            return self.render_to_response({
                'requestion': requestion,
                'benefits_form': benefits_form,
                'documents': self.get_own_documents(requestion),
            })


class BenefitCategoryChange(OperatorRequestionCheckIdentityMixin,
    OperatorRequestionEditMixin, AnonymBenefitCategoryChange):
    template_name = 'operator/requestion_benefitcategory_change.html'

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
                    reverse('operator_requestion_info',
                            kwargs={'requestion_id': requestion.id}))
        else:
            return self.render_to_response(
                {'requestion': requestion, 'form': form})


class PreferredSadiksChange(OperatorRequestionCheckIdentityMixin,
    OperatorRequestionEditMixin, AnonymPreferredSadiksChange):
    u"""
    изменение приоритетных ДОУ у заявки оператором
    """
    template_name = "operator/requestion_preferredsadiks_change.html"

    def post(self, request, requestion):
        form = PreferredSadikForm(instance=requestion, data=request.POST)
        if form.is_valid():
            if form.has_changed():
                # TODO: Добавить изящества в составление конеткста для логов
                pref_sadiks = set(requestion.pref_sadiks.all())
                requestion = form.save()
                new_pref_sadiks = set(requestion.pref_sadiks.all())
                added_pref_sadiks = new_pref_sadiks - pref_sadiks
                removed_pref_sadiks = pref_sadiks - new_pref_sadiks
                context_dict = {
                    'changed_data': form.changed_data,
                    'cleaned_data': form.cleaned_data,}
                Logger.objects.create_for_action(
                    CHANGE_PREFERRED_SADIKS_BY_OPERATOR,
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
                reverse('operator_requestion_info',
                    kwargs={'requestion_id': requestion.id}))
        return self.render_to_response({
            'requestion': requestion,
            'form': form,
            })


class DocumentsChange(OperatorRequestionCheckIdentityMixin,
    OperatorRequestionEditMixin, AnonymDocumentsChange):
    template_name = 'operator/requestion_documents_change.html'

    def post(self, request, requestion):
#        переопределяем formset для под-я всех новых документов
        DocumentFormset = generic_inlineformset_factory(EvidienceDocument,
            form=DocumentForm,
            formset=DocumentGenericInlineFormSet,
            exclude=['confirmed', ], extra=1)

        formset = DocumentFormset(request.POST,
            queryset=EvidienceDocument.objects.filter(
                template__destination=BENEFIT_DOCUMENT),
            instance=requestion)

        if formset.is_valid():
            if formset.has_changed():
                formset.save()
                messages.info(request, u'''Документы были изменены''')
                Logger.objects.create_for_action(
                        CHANGE_DOCUMENTS_BY_OPERATOR,
                        context_dict={'benefit_documents': requestion.evidience_documents().filter(
                            template__destination=BENEFIT_DOCUMENT)},
                        extra={'user': request.user, 'obj': requestion})

            else:
                messages.info(request, u'''Документы не были изменены''')
            return HttpResponseRedirect(reverse('operator_requestion_info',
                    kwargs={'requestion_id': requestion.id}))
        else:
            return self.render_to_response({
                'formset': formset,
                'requestion': requestion,
                'confirmed': requestion.evidience_documents().confirmed(),
            })


class SetIdentityDocument(OperatorRequestionMixin, TemplateView):
    template_name = u"operator/set_identity_document.html"

    def dispatch(self, request, requestion_id):
        redirect_to = request.REQUEST.get('next', '')
        self.redirect_to = check_url(redirect_to,
            reverse('operator_requestion_info',
                    kwargs={'requestion_id': requestion_id}))
        return super(SetIdentityDocument, self).dispatch(request, requestion_id)

    def check_permissions(self, request, requestion):
        return (requestion.evidience_documents().filter(fake=True,
                template__destination=REQUESTION_IDENTITY) and
            super(SetIdentityDocument, self).check_permissions(
                request, requestion))

    def get(self, request, requestion):
        form = RequestionIdentityDocumentForm(instance=requestion)
        return self.render_to_response(
            {'form': form, 'requestion': requestion,
                'redirect_to': self.redirect_to})

    def post(self, request, requestion):
        form = RequestionIdentityDocumentForm(instance=requestion,
            data=request.POST)
        if form.is_valid():
            form.save()
            # после указания документа можно удалить временный
            requestion.evidience_documents().filter(fake=True).delete()
            messages.info(request, u'Для заявки был указан идентифицирующий документ.')
            Logger.objects.create_for_action(
                CHANGE_DOCUMENTS_BY_OPERATOR,
                context_dict={'requestion_documents': requestion.evidience_documents().filter(
                    template__destination=REQUESTION_IDENTITY)},
                extra={'user': request.user, 'obj': requestion})
            return HttpResponseRedirect(self.redirect_to)
        return self.render_to_response({'form': form, 'requestion': requestion,
            'redirect_to': self.redirect_to})


# -----------------------------
#  Изменение статуса заявки
# -----------------------------
class RequestionStatusChange(RequirePermissionsMixin, TemplateView):
    template_name = 'operator/requestion_status_change.html'

    def check_permissions(self, request, requestion):
        # Ограничение прав для пользователя
        if request.user.is_authenticated():
            if request.user.is_requester():
                if requestion.profile.user != request.user:
                    return False

            if not self.required_permissions:
                # Если права пустые, значит переход системный (автоматический),
                # пользователь не может его инициировать
                return False
            else:
                # Преопределена проверка прав, чтобы одно и то же действие
                # могли выплонять разные роли.
                # В оригинальном CheckPermissions вместо ``any`` делается проверка на ``all``
                permission_granted = any([request.user.has_perm("auth.%s" % req)
                        for req in self.required_permissions])

            # Проверка дополнительных условий, заданных в callback
            if self.transition:
                if callable(self.transition.permission_cb):
                    if request.method == 'POST':
                        form = self.get_confirm_form(self.transition.index,
                            requestion=requestion, data=request.POST)
                        if form.is_valid():
                            cb_result = self.transition.permission_cb(
                                request.user, requestion, self.transition, request=request, form=form)
                            return cb_result and permission_granted
                    else:
                        cb_result = self.transition.permission_cb(
                            request.user, requestion, self.transition, request=request, form=None)
                        return cb_result and permission_granted
                return permission_granted

        return False

    def default_redirect_to(self, requestion):
        return reverse('operator_requestion_info', args=[requestion.id])

    def dispatch(self, request, requestion_id, dst_status):
        u"""
        Метод переопределен, чтобы сохранить в атрибутах ``transition``
        """
        requestion = get_object_or_404(Requestion, id=requestion_id)

        redirect_to = request.REQUEST.get('next', '')
        self.redirect_to = check_url(redirect_to, self.default_redirect_to(requestion))

        transition_indexes = workflow.available_transitions(src=requestion.status, dst=int(dst_status))
        if transition_indexes:
            self.transition = workflow.get_transition_by_index(transition_indexes[0])
        else:
            self.transition = None

        # копирование ролей из workflow в проверку прав
        if self.transition:
            # Если на перевод есть права
            if self.transition.required_permissions:
                temp_copy = self.transition.required_permissions[:]
                # Пропустить публичный доступ ``ANONYMOUS_PERMISSION``
                if Transition.ANONYMOUS_PERMISSION in temp_copy:
                    temp_copy.remove(Transition.ANONYMOUS_PERMISSION)
                self.required_permissions = temp_copy

            # Если переод только внутрисистемный, запретить его выполнение
            else:
                self.required_permissions = None

            #задаем шаблон в зависимости от типа изменения статуса
            self.template_name = self.get_custom_template_name() or self.template_name

        response = super(RequestionStatusChange, self).dispatch(request, requestion)
        # если проверка прав прошла, то проверяем есть ли у заявки документы
        if isinstance(response, TemplateResponse):
            if not requestion.evidience_documents().filter(
                    template__destination=REQUESTION_IDENTITY).exists():
                return HttpResponseRedirect(
                    u'%s?next=%s' %
                    (reverse('operator_requestion_set_identity_document',
                             kwargs={'requestion_id': requestion_id}),
                     urlquote(request.get_full_path()))
                )
        return response

    def get_confirm_form(self, transition_index, requestion=None, data=None,
            initial=None):
        form_class = self.transition.confirmation_form_class
        if not form_class:
            form_class = ConfirmationForm
        if isinstance(form_class, ModelFormMetaclass):
            form = form_class(
                requestion=requestion, data=data, initial=initial)
        else:
            form = form_class(requestion=requestion, data=data, initial=initial)
        return form

    def get_context_data(self, requestion, **kwargs):
        form = self.get_confirm_form(self.transition.index,
            requestion=requestion,
            initial={'transition': self.transition.index})
        return {
            'form': form,
            'transition': self.transition,
        }

    def get_custom_template_name(self):
        try:
            template = loader.get_template('operator/status_change/%s.html' % self.transition.index)
            return template.name
        except TemplateDoesNotExist:
            return None

    def get(self, request, requestion, *args, **kwargs):
        context = self.get_context_data(requestion)
        context.update({
            'requestion': requestion,
            'redirect_to': self.redirect_to
        })
        return self.render_to_response(context)

    def post(self, request, requestion, *args, **kwargs):
        if request.POST.get('confirmation') == "no":
            messages.info(request, u"Статус заявки не был изменен")
            return HttpResponseRedirect(self.redirect_to)
        context = self.get_context_data(requestion)
        form = self.get_confirm_form(self.transition.index,
            requestion=requestion, data=request.POST,
            initial={'transition': self.transition.index})
        context.update({
            'form': form,
            'requestion': requestion,
            'redirect_to': self.redirect_to
        })

        if form.is_valid():
            pre_status_change.send(sender=Requestion, request=request,
                requestion=requestion, transition=self.transition, form=form)

            # Момент истины
#            если ModelForm, то сохраняем
            if isinstance(form.__class__, ModelFormMetaclass):
                requestion = form.save(commit=False)
                requestion.status = self.transition.dst
                requestion.save()
                form.save_m2m()
            else:
                requestion.status = self.transition.dst
                requestion.save()

            post_status_change.send(sender=Requestion, request=request,
                requestion=requestion, transition=self.transition, form=form)
            return HttpResponseRedirect(self.redirect_to)
        else:
            return self.render_to_response(context)


class FindProfileForRequestion(OperatorRequestionCheckIdentityMixin,
        OperatorRequestionEditMixin, AnonymRequestionSearch):
    template_name = "operator/find_profile_for_requestion.html"
    initial_query = Profile.objects.filter(
        user__user_permissions__codename=REQUESTER_PERMISSION[0])
    form = ProfileSearchForm
    field_weights = {
        'requestion__requestion_number__exact': 5,
        'first_name__icontains': 1,
    }

    def get_context_data(self, **kwargs):
        return {
            'params': kwargs,
            'requestion': kwargs.get('requestion'),
            'form': self.form(),
        }


class EmbedRequestionToProfile(OperatorRequestionCheckIdentityMixin,
        OperatorRequestionEditMixin, TemplateView):
    template_name = u"operator/embed_requestion_to_profile.html"

    def get_context_data(self, **kwargs):
        return {
            'requestion': kwargs.get('requestion'),
            'params': kwargs
        }

    def check_permissions(self, request, requestion, profile):
        if super(EmbedRequestionToProfile, self).check_permissions(
                request, requestion, profile) and profile.user.is_requester()\
                and requestion.profile != profile:
            return True
        return False

    def dispatch(self, request, requestion_id, profile_id):
        profile = get_object_or_404(Profile, id=profile_id)
        return super(EmbedRequestionToProfile, self).dispatch(
            request, requestion_id=requestion_id, profile=profile)

    def get(self, request, requestion, profile):
        form = BaseConfirmationForm()
        context = self.get_context_data(
            requestion=requestion, profile=profile)
        context.update({'form': form})
        return self.render_to_response(context)

    def post(self, request, requestion, profile):

        form = BaseConfirmationForm(request.POST)
        if form.is_valid():
            reason = form.cleaned_data.get('reason')
            requestion.embed_requestion_to_profile(
                profile, request.user, reason)
            messages.info(request, u'Заявка %s была прикреплена к профилю' %
                    requestion.requestion_number)
            return HttpResponseRedirect(
                reverse("operator_requestion_info",
                    kwargs={'requestion_id': requestion.id}))
        context = self.get_context_data(requestion=requestion, profile=profile)
        context.update({'form': form})
        return self.render_to_response(context)


class GenerateBlank(OperatorRequestionMixin, GenerateBlankBase):
    templates_by_type = {
        'registration': u"operator/blanks/registration.html",
        'change_info': u"operator/blanks/change_info.html",
        'change_preferred_sadiks': u"operator/blanks/change_preferred_sadiks.html",
        'remove_registration': u"operator/blanks/remove_registration.html",
        }


class GenerateProfilePassword(OperatorPermissionMixin, View):

    def post(self, request, profile_id):
        profile = get_object_or_404(Profile, id=profile_id)
        user = profile.user
        form = HiddenConfirmation(request.POST)
        if form.is_valid() and form.cleaned_data.get('action') == 'reset_password':
            password = User.objects.make_random_password()
            user.set_password(password)
            user.save()
            result = generate_pdf(template_name='operator/blanks/reset_password.html',
                                  context_dict={'password': password, 'media_root': settings.MEDIA_ROOT,
                                                'profile': profile})
            response = HttpResponse(result.getvalue(), mimetype='application/pdf')
            return response


class ChangeRequestionLocation(OperatorPermissionMixin, View):

    def post(self, request, requestion_id):
        requestion = get_object_or_404(Requestion, id=requestion_id)
        if requestion.cast != REQUESTION_TYPE_IMPORTED or requestion.status != STATUS_ON_DISTRIBUTION:
            raise Http404
        if request.is_ajax():
            location_form = ChangeLocationForm(instance=requestion, data=request.POST)
            if location_form.is_valid():
                if location_form.has_changed():
                    location_form.save()
                    Logger.objects.create_for_action(CHANGE_REQUESTION_LOCATION,
                        context_dict={'changed_fields': location_form.changed_data,
                    'requestion': requestion},
                        extra={'user': request.user, 'obj': requestion})
                return HttpResponse(content=json.dumps({'ok': True}),
                        mimetype='text/javascript')
            return HttpResponse(content=json.dumps({'ok': False}),
                        mimetype='text/javascript')

        else:
            return HttpResponseBadRequest()


class SocialProfilePublic(OperatorPermissionMixin, AccountSocialProfilePublic):

    def dispatch(self, request, profile_id):
        profile = get_object_or_404(Profile, id=profile_id)
        return super(AccountSocialProfilePublic, self).dispatch(request, profile)