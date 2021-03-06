# -*- coding: utf-8 -*-
import random
import string

from django.core.management.base import BaseCommand
from django.contrib.auth.models import User

from sadiki.core.models import Benefit
from sadiki.logger.models import Logger, LoggerMessage
from personal_data.models import ChildPersData, UserPersData


class Command(BaseCommand):
    help_text = '''Usage: manage.py remove_personal_data'''

    def handle(self, *args, **options):
        print "Изменяем описание льгот"
        benefits = Benefit.objects.all()
        for benefit in benefits:
            benefit.name = u"Льгота №{} категории {}".format(
                benefit.id, benefit.category.id)
            benefit.description = benefit.name
            benefit.save()

        print "Изменяем содержимое логов о персональных данных"
        pdata_log_ids = Logger.objects.filter(action_flag__gt=200)
        pdata_log_msgs = LoggerMessage.objects.filter(logger__in=pdata_log_ids)
        for msg in pdata_log_msgs:
            msg.message = u"Изменение персональных данных"
            msg.save()

        men_data = {
            'first_names': ['Вася', 'Федя', 'Коля', 'Степан', 'Алексей',
                            'Дмитрий', 'Егор', 'Владимир', 'Влад', 'Александр',
                            'Виталий', 'Иван', 'Евгений', 'Игорь', 'Андрей'],
            'second_names': ['Васильевич', 'Федорович', 'Николаевич',
                             'Степанович', 'Алексеевич', 'Дмитриевич',
                             'Егорович', 'Владимирович', 'Владиславович',
                             'Александрович', 'Витальевич', 'Иванович',
                             'Евгеньевич', 'Игоревич', 'Андреевич'],
            'last_names': ['Иванов', 'Сидоров', 'Петров', 'Буйко', 'Савельев',
                           'Ищенко', 'Брут', 'Боровик', 'Весельев', 'Дворский',
                           'Симонов', 'Леантович', 'Саломатов', 'Козочкин']
        }
        women_data = {
            'first_names': ['Аня', 'Ирина', 'Маша', 'Света', 'Алена',
                            'Ангелина', 'Катя', 'Вера', 'Влада', 'Надежда',
                            'Василиса', 'Вика', 'Евгения', 'Юлия', 'Алефтина'],
            'second_names': ['Васильевна', 'Федоровна', 'Николаевна',
                             'Степановна', 'Алексеевна', 'Дмитриевна',
                             'Егоровна', 'Владимировна', 'Владиславовна',
                             'Александровна', 'Витальевна', 'Ивановна',
                             'Евгеньевна', 'Игоревна', 'Андреевна'],
            'last_names': ['Иванова', 'Сидорова', 'Петрова', 'Буйко', 'Ищенко',
                           'Савельева', 'Брут', 'Боровик', 'Весельева',
                           'Дворская', 'Симонова', 'Леантович', 'Саломатова',
                           'Козочкина']
        }

        address_data = {
            'settlement': ['Нью-Йорк', 'Лондон', 'Москва', 'деревня Гадюкино',
                           'Париж', 'Оттава', 'Рим', 'Прага', 'Каир'],
            'street': ['Веселая', 'Тенистая', '5-я Авеню', 'Улиточная',
                       'генерала Уранова', 'Светлая', 'Ленина', 'Пушкина'],
        }

        print "Изменяем персональные данные детей"
        pdata = {u"М": men_data, u"Ж": women_data}
        child_data = ChildPersData.objects.all()
        for record in child_data:
            sex = record.application.sex or random.choice(pdata.keys())
            record.first_name = random.choice(pdata[sex]['first_names'])
            record.second_name = random.choice(pdata[sex]['second_names'])
            record.last_name = random.choice(pdata[sex]['last_names'])
            record.save()

        print "Изменяем персональные данные пользователей"
        pers_data = UserPersData.objects.all()
        for record in pers_data:
            sex = random.choice(pdata.keys())
            record.first_name = random.choice(pdata[sex]['first_names'])
            record.second_name = random.choice(pdata[sex]['second_names'])
            record.last_name = random.choice(pdata[sex]['last_names'])
            record.settlement = random.choice(address_data['settlement'])
            record.street = random.choice(address_data['street'])
            record.house = str(random.choice(range(1, 99)))
            record.phone = ''.join([random.choice(string.digits)
                                    for _ in xrange(11)])
            record.save()

        print "Удаляем почту"
        User.objects.all().update(email='')
