# -*- coding: utf-8 -*-
from django.test import TestCase
from django.core import management
from django.contrib.auth.models import User, Group, Permission
from django.core.urlresolvers import reverse

from sadiki.core.models import Profile, BenefitCategory, Requestion, Sadik, \
    SadikGroup, Preference, PREFERENCE_IMPORT_FINISHED, Address
from sadiki.core.permissions import OPERATOR_GROUP_NAME, SUPERVISOR_GROUP_NAME, \
    SADIK_OPERATOR_GROUP_NAME, DISTRIBUTOR_GROUP_NAME


class CoreViewsTest(TestCase):
    fixtures = ['sadiki/core/fixtures/test_initial.json', ]

    @classmethod
    def setUpClass(cls):
        management.call_command('update_initial_data')

    @classmethod
    def tearDownClass(cls):
        Permission.objects.all().delete()
        Group.objects.all().delete()
        BenefitCategory.objects.all().delete()
        Sadik.objects.all().delete()
        Address.objects.all().delete()

    def setUp(self):
        Preference.objects.create(key=PREFERENCE_IMPORT_FINISHED)
        self.operator = User(username='operator')
        self.operator.set_password("password")
        self.operator.save()
        Profile.objects.create(user=self.operator)
        operator_group = Group.objects.get(name=OPERATOR_GROUP_NAME)
        sadik_operator_group = Group.objects.get(name=SADIK_OPERATOR_GROUP_NAME)
        distributor_group = Group.objects.get(name=DISTRIBUTOR_GROUP_NAME)
        self.operator.groups = (operator_group, sadik_operator_group,
                                distributor_group)
        self.supervisor = User(username="supervisor")
        self.supervisor.set_password("password")
        self.supervisor.save()
        Profile.objects.create(user=self.supervisor)
        supervisor_group = Group.objects.get(name=SUPERVISOR_GROUP_NAME)
        self.supervisor.groups = (supervisor_group,)

        self.requester = User.objects.create_user(username='requester',
                                                  password='123456q')
        permission = Permission.objects.get(codename=u'is_requester')
        self.requester.user_permissions.add(permission)
        Profile.objects.create(user=self.requester)
        self.requester.save()

    def tearDown(self):
        Requestion.objects.all().delete()
        SadikGroup.objects.all().delete()
        Sadik.objects.all().delete()
        User.objects.all().delete()

    def test_requestion_add(self):
        """
        Проверяем корректрость работы ключа token, хранящегося в сессии
        пользователя.
        """
        management.call_command('generate_sadiks', 10)
        kgs = Sadik.objects.all()
        form_data = {
            'core-evidiencedocument-content_type-object_id-TOTAL_FORMS': '1',
            'core-evidiencedocument-content_type-object_id-INITIAL_FORMS': '0',
            'core-evidiencedocument-content_type-object_id-MAX_NUM_FORMS':
                '1000',
        }
        self.assertTrue(self.client.login(username=self.operator.username,
                                          password='password'))
        # до посещения страницы с формой, токена нет
        self.assertIsNone(self.client.session.get('token', None))
        # заявка не сохраняется, редирект на страницу добавления заявки
        create_response = self.client.post(
            reverse('anonym_registration'), {
                'name': 'Ann',
                'sex': 'Ж',
                'birth_date': '07.06.2014',
                'admission_date': '01.01.2014',
                'template': '2',
                'document_number': 'II-ИВ 016809',
                'areas': '1',
                'location': 'POINT (60.115814208984375 55.051432600719835)',
                'pref_sadiks': [str(kgs[0].id), str(kgs[1].id)],
            })
        self.assertEqual(create_response.status_code, 302)
        self.assertRedirects(create_response,
                             reverse('anonym_registration'))
        self.assertIsNotNone(self.client.session.get('token'))

        # зашли на страницу с формой, токен появился
        response = self.client.get(reverse('anonym_registration'))
        self.assertEqual(response.status_code, 200)
        token = response.context['form']['token'].value()
        self.assertIsNotNone(self.client.session.get('token'))
        self.assertIsNone(self.client.session['token'][token])

        # успешный post, создается заявка, токен удаляется
        form_data.update(
            {'name': 'Ann',
             'sex': 'Ж',
             'birth_date': '07.06.2014',
             'admission_date': '01.01.2014',
             'template': '2',
             'document_number': 'II-ИВ 016809',
             'areas': '1',
             'location': 'POINT (60.115814208984375 55.051432600719835)',
             'token': token,
             'pref_sadiks': [str(kgs[0].id), str(kgs[1].id)], }
        )
        create_response = self.client.post(
            reverse('anonym_registration'), form_data)
        requestion = create_response.context['requestion']
        self.assertEqual(create_response.status_code, 302)
        self.assertRedirects(
            create_response,
            reverse('operator_requestion_info', args=(requestion.id,)))
        self.assertIsNotNone(self.client.session.get('token', None))
        self.assertEqual(self.client.session['token'][token], requestion.id)

        # пробуем с таким же токеном еще раз, перенаправляет на
        # заявку c id, хранящемся в сессии по токену, если такая имеется
        form_data.update(
            {'name': 'Mary',
             'birth_date': '06.06.2014',
             'template': '2',
             'document_number': 'II-ИВ 016808',
             'areas': '2',
             'token': token, }
        )
        create_response = self.client.post(
            reverse('anonym_registration'), form_data)
        self.assertEqual(create_response.status_code, 302)
        token_req_num = self.client.session['token'][token]
        self.assertRedirects(
            create_response,
            reverse('operator_requestion_info', args=(token_req_num,)))
        self.assertIsNotNone(self.client.session.get('token'))

        # пробуем с неверным токеном еще раз, перенаправляет на
        # страницу добавления заявки
        form_data.update(
            {'name': 'Mary',
             'birth_date': '06.06.2014',
             'template': '2',
             'document_number': 'II-ИВ 016808',
             'areas': '2',
             'token': 'some-wrong-token', }
        )
        create_response = self.client.post(
            reverse('anonym_registration'), form_data)
        self.assertEqual(create_response.status_code, 302)
        self.assertRedirects(
            create_response,
            reverse('anonym_registration'))
        self.assertIsNotNone(self.client.session.get('token'))
        self.assertEqual(len(self.client.session['token']), 3)