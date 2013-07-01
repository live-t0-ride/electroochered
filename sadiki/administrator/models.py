# -*- coding: utf-8 -*-
import sys
from django.conf import settings
from django.contrib.auth.models import User, Permission
from django.contrib.contenttypes import generic
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.core.files.storage import FileSystemStorage
from django.db import models, transaction
from django.template.loader import render_to_string
from django.utils.log import getLogger
from hex_storage import HexFileSystemStorage
from sadiki.administrator.import_plugins import INSTALLED_FORMATS, \
    SADIKS_FORMATS
from sadiki.administrator.utils import get_xlwt_style_list
from sadiki.core.geocoder import Yandex
from sadiki.core.importpath import importpath
from sadiki.core.models import Requestion, Sadik, Address, EvidienceDocument, EvidienceDocumentTemplate, REQUESTION_IDENTITY, REQUESTION_TYPE_IMPORTED
from sadiki.core.utils import get_unique_username
from xlutils.copy import copy
import datetime
import os
import tempfile
import xlrd
import xlwt


class Photo(models.Model):
    name = models.CharField(verbose_name=u'название', max_length=255)
    description = models.CharField(verbose_name=u'описание', max_length=255,
        blank=True, null=True)
    image = models.ImageField(verbose_name=u'фотография',
        upload_to='upload/sadik/images/', blank=True)
    content_type = models.ForeignKey(ContentType)
    object_id = models.PositiveIntegerField()
    content_object = generic.GenericForeignKey()

TABLE_TYPE_CHOICES = (
    (0, u'Очередники'),
    (1, u'Первоочередники'),
    (2, u'Внеочередники'),
)

#===============================================================================
# Импорт данных
#===============================================================================

min_birth_date = lambda: datetime.date.today().replace(
    year=datetime.date.today().year - settings.MAX_CHILD_AGE)

class CellParserMismatch(Exception):

    def __init__(self):
        self.messages = [u'Неверный тип поля', ]

class ErrorRow(list):

    def __init__(self, data, index, logic_exception=None):
        self.row_index = index
        self.logic_exception = logic_exception
        super(ErrorRow, self).__init__(data)

class CellParser(object):
    parser_type = None

    def __init__(self, value, datemode):
        self.value = value
        self.datemode = datemode

    def to_python(self):
        """return python object or raise ValidationError"""
        raise NotImplementedError('Override this method in children class')

class Format(object):

    cells = []  # override this

    # xls reading options
    start_line = 0
    sheet_num = 0

    def __init__(self, document, name=None):
        """
        name - internal format name
        cell_parser - iterable object, contains row cells for validation
        for example:
            [(cell1,),
             (cell2,),
             (cell3_1, cell3_2),
             (cell4,)]
        If validation in cell3_1 fails, format will try to validate cell3_2.
        """
        self.name = name
        self.document = document
        self.cell_data = []
        self.sheet = self.document.sheet_by_index(self.sheet_num)

    def to_python(self, data_row):
        """
        Returns python object with all required data
        Object should not expect any Exception subclasses in data_row
        Should return tuple of objects:
            requestion, profile, sadik_number_list
        """
        raise NotImplementedError('Override this method in children class')

    def _run_cell_parser(self, cell_parser, cell_data):
        """Validate cell data through parser"""
        if cell_parser.parser_type == cell_data.ctype:
            return cell_parser(cell_data.value, self.document.datemode).to_python()
        else:
            raise CellParserMismatch()

    def __iter__(self):
        return self.next()

    def next(self):
        # per-row validation
        for rownum in range(self.start_line, self.sheet.nrows):
            data_row = self.sheet.row_slice(rownum)[:len(self.cells)]
            parsed_data = []

            # per-cell validation
            for i, cell_data in enumerate(data_row):
                # temp variables
                exception = None
                value = None
                ok = False  # bool if any value returned
                # run all parsers
                for cell_parser in self.cells[i]['parsers']:
                    try:
                        value = self._run_cell_parser(cell_parser, cell_data)
                        ok = True
                        break
                    except ValidationError, e:
                        if exception is None:
                            exception = e
                        else:
                            pass  # go to next cellparser
                    except CellParserMismatch:
                        pass  # go to next cellparser

                # store value and exception data
                if (not ok) and (exception is None):
                    exception = CellParserMismatch()
                if ok:
                    parsed_data.append(value)
                else:
                    parsed_data.append(exception)

            yield parsed_data

def validate_fields_length(obj):
    u"""
    проверяем, что длина строки не превышает макс. длины поля
    """
    errors = []
    for field in obj._meta.fields:
        if (all((field.max_length, field.value_from_object(obj))) and
            len(field.value_from_object(obj)) > field.max_length):
            errors.append(u'В поле "%s" должно быть не больше %d символов' %
                (field.verbose_name, field.max_length))
    return errors


class RequestionLogic(object):

    def __init__(self, format_doc, fake=False):
        """
        Describes main buisness logic in import process
        format_doc - instance of subclass of Format
        """
        self.format_doc = format_doc
        self.errors = []
        self.new_identificators = []
        self.fake = fake
        self.requestion_documents = []
        self.requestion_document_template = EvidienceDocumentTemplate.objects.filter(
            destination=REQUESTION_IDENTITY)[0]

    def validate(self):
        """
        Run through cells, if cell is valid, store python value,
        if not - store error information
        """
        for index, parsed_row in enumerate(self.format_doc):
            cell_errors = any([issubclass(type(cell), Exception) for cell in parsed_row])
            try:
                self.validate_record(self.format_doc.to_python(parsed_row), cell_errors, index)
            except ValidationError, e:
                logic_errors = e
            else:
                logic_errors = None
            if cell_errors or logic_errors:
                self.errors.append(ErrorRow(parsed_row, index + self.format_doc.start_line, logic_errors))

    def validate_record(self, data_tuple, cell_errors, row_index):
        from sadiki.core.workflow import REQUESTION_IMPORT
        from sadiki.core.workflow import IMPORT_PROFILE
        requestion, profile, areas, sadik_number_list, address_data, benefits, document, errors = data_tuple
        address = Address(**address_data)
        requestion.profile = profile
#        если у заявки не указано время регистрации, то устанавливаем 9:00
        if type(requestion.registration_datetime) is datetime.date:
            requestion.registration_datetime = datetime.datetime.combine(
                requestion.registration_datetime, datetime.time(9, 0))
        requestion = self.change_registration_datetime_coincedence(requestion)
        if document:
            try:
                self.validate_document_duplicate(document)
            except ValidationError, e:
                errors.extend(e.messages)
        if requestion.registration_datetime:
            try:
                self.validate_registration_date(requestion)
            except ValidationError, e:
                errors.extend(e.messages)
        if requestion.registration_datetime and requestion.birth_date:
            try:
                self.validate_dates(requestion)
            except ValidationError, e:
                errors.extend(e.messages)
        if sadik_number_list:
            try:
                preferred_sadiks = self.validate_sadik_list(areas, sadik_number_list)
            except ValidationError, e:
                errors.extend(e.messages)
            try:
                self.validate_admission_date(requestion)
            except ValidationError, e:
                errors.extend(e.messages)
        else:
            preferred_sadiks = []
        length_errors = []
        length_errors.extend(validate_fields_length(profile))
        length_errors.extend(validate_fields_length(requestion))
        if document:
            length_errors.extend(validate_fields_length(document))
        if length_errors:
            errors.extend(length_errors)
        if errors:
            raise ValidationError(errors)
        else:
#            ошибок нет, можно сохранять объекты
            if not cell_errors and not self.fake:
                user = User.objects.create_user(get_unique_username(), '')
                user.set_username_by_id()
                user.save()
                permission = Permission.objects.get(codename=u'is_requester')
                user.user_permissions.add(permission)
                profile.user = user
                profile.save()
                requestion.location_properties = address.text
                requestion.profile = profile
                requestion.cast = REQUESTION_TYPE_IMPORTED
                coords = requestion.geocode_address(Yandex)
                if not coords:
                    if settings.REGION_NAME:
                        geocoder = Yandex()
                        coords = geocoder.geocode(settings.REGION_NAME)
                if coords:
                    requestion.set_location(coords)
                requestion.save()
                if not document:
                    document_number = "TMP_%07d" % row_index
                    self.new_identificators.append({'row_index': row_index + self.format_doc.start_line,
                                                    'document_number': document_number})
                    document = EvidienceDocument(
                        template=self.requestion_document_template,
                        document_number=document_number, confirmed=True,
                        fake=True)
                document.content_object = requestion
                document.save()
                if areas:
                    requestion.areas.add(*areas)
                for sadik in preferred_sadiks:
                    requestion.pref_sadiks.add(sadik)
#                добавляем льготы
                if benefits:
                    for benefit in benefits:
                        requestion.benefits.add(benefit)
                        requestion.save()
                context_dict = {'user': user, 'profile': profile,
                                'requestion': requestion,
                                'pref_sadiks': preferred_sadiks,
                                'areas': areas, 'benefits': benefits}
                from sadiki.logger.models import Logger
                Logger.objects.create_for_action(IMPORT_PROFILE,
                    context_dict={'user': user, 'profile': profile},
                    extra={'obj': profile})
                Logger.objects.create_for_action(REQUESTION_IMPORT,
                    context_dict=context_dict,
                    extra={'obj': requestion,
                        'added_pref_sadiks': preferred_sadiks})

    def validate_document_duplicate(self, document):
        errors = []
        if document.document_number in self.requestion_documents:
            errors.append(u'Заявка с документом "%s" уже встречается в файле' % document.document_number)
        else:
            self.requestion_documents.append(document.document_number)
            if EvidienceDocument.objects.filter(document_number=document.document_number, confirmed=True).exists():
                errors.append(u'Документ "%s" уже встречается в системе и подтвержден' % document.document_number)
        if errors:
            raise ValidationError(errors)

    def validate_registration_date(self, requestion):
        u"""заявки должны быть поданы до теукщей даты"""
        if datetime.date.today() < requestion.registration_datetime.date():
            raise ValidationError(
                u'Дата регистрации не может быть больше текущей даты.')
        elif datetime.date.today() == requestion.registration_datetime.date():
            raise ValidationError(
                u'Дата регистрации не может совпадать с текущей датой.')

    def validate_dates(self, requestion):
        u"""проверка, что дата рождения попадает в диапазон для зачисления и
        дата регистрации больше даты рождения"""
        if datetime.date.today() < requestion.birth_date or requestion.birth_date <= min_birth_date():
            raise ValidationError(u'Возраст ребёнка не подходит для зачисления в ДОУ.')
        if requestion.registration_datetime.date() < requestion.birth_date:
            raise ValidationError(u'Дата регистрации меньше даты рождения ребёнка.')

    def validate_sadik_list(self, areas, sadik_number_list):
        u"""проверяем, номера ДОУ"""
        errors = []
        preferred_sadiks = []
        if type(sadik_number_list) is list:
            for sadik_number in sadik_number_list:
                sadiks = Sadik.objects.filter(
                    identifier=sadik_number,)
                if sadiks.count() == 1:
                    preferred_sadiks.append(sadiks[0])
                elif not sadiks.count():
                    errors.append(
                        u'В системе нет ДОУ с номером %s' % sadik_number)
                elif sadiks.count() >= 2:
                    errors.append(
                        u'В данной территориальной области есть несколько ДОУ с номером %s' % sadik_number)
        if errors:
            raise ValidationError(errors)
        else:
            return preferred_sadiks

    def validate_admission_date(self, requestion):
        if requestion.admission_date and (requestion.admission_date.year >
                datetime.date.today().year + settings.MAX_CHILD_AGE):
            raise ValidationError(u'Для желаемого года зачисления указано слишком большое значение.')

    def change_registration_datetime_coincedence(self, requestion):
        u"""Если для данного района уже есть заявка с такой датой и временем,то
            для данной заявки добавить 10 минут"""
#        если в районе есть заявки с такой же датой и временем регистрации
        if Requestion.objects.filter(
            registration_datetime=requestion.registration_datetime).count():
#            получаем последнюю заявку, поданную в этот день
            last_requestion = Requestion.objects.filter(
                registration_datetime__year=requestion.registration_datetime.year,
                registration_datetime__month=requestion.registration_datetime.month,
                registration_datetime__day=requestion.registration_datetime.day,
                ).order_by('-registration_datetime')[0]
            requestion.registration_datetime = last_requestion.registration_datetime + \
                datetime.timedelta(minutes=10)
        return requestion

    def save_xls_results(self, path_to_file):
        u"""в UPLOAD_ROOT создаётся файл с именем file_name в котором строки с ошибками красные"""
        rb = self.format_doc.document
        rb_sheet = rb.sheet_by_index(0)
        wb = copy(rb)
        ws = wb.get_sheet(0)
        styles = get_xlwt_style_list(rb)
        for error in self.errors:
            row = rb_sheet.row(error.row_index)
            style = xlwt.easyxf('pattern: pattern solid, fore_colour red; align: horiz centre, vert centre; borders: top thin, bottom thin, left thin, right thin;')
            for i, cell in enumerate(row):
                style.num_format_str = styles[cell.xf_index].num_format_str
                ws.write(error.row_index, i, cell.value, style)
        for identificator in self.new_identificators:
            ws.write(identificator["row_index"],
                     self.format_doc.document_cell_index, identificator["document_number"])
        wb.save(path_to_file)

class SadikLogic(object):
    sadiks_identifiers = []
    errors = []

    def __init__(self, format_doc, area, fake=False):
        self.format_doc = format_doc
        self.area = area
        self.fake = fake

    def validate(self):
        for index, parsed_row in enumerate(self.format_doc):
            cell_errors = any([issubclass(type(cell), Exception) for cell in parsed_row])
            try:
                self.validate_record(self.format_doc.to_python(parsed_row), cell_errors=cell_errors)
            except ValidationError, e:
                logic_errors = e
            else:
                logic_errors = None
            if cell_errors or logic_errors:
                self.errors.append(ErrorRow(parsed_row, index + self.format_doc.start_line, logic_errors))

    def validate_record(self, data_tuple, cell_errors):
        sadik_object, address_data, age_groups = data_tuple
        errors = []
        if sadik_object.identifier:
            try:
                self.validate_identifier(sadik_object)
            except ValidationError, e:
                errors.extend(e.messages)
        if errors:
            raise ValidationError(errors)
        else:
            if not cell_errors:
                self.import_sadik(sadik_object, address_data, age_groups)

    def validate_identifier(self, sadik_object):
        errors = []
        if sadik_object.identifier in self.sadiks_identifiers:
            errors.append(u'ДОУ с идентификатором "%s" уже встречается' % sadik_object.identifier)
        else:
            self.sadiks_identifiers.append(sadik_object.identifier)
        if Sadik.objects.filter(identifier=sadik_object.identifier).exists():
            errors.append(u'ДОУ с идентификатором "%s" уже есть в системе' % sadik_object.identifier)
        if errors:
            raise ValidationError(errors)

    def import_sadik(self, sadik_obj, address_data, age_groups):
        if not self.fake:
            address = Address.objects.get_or_create(**address_data)[0]
            sadik_obj.address = address
            sadik_obj.save()
            sadik_obj.age_groups = age_groups

    def save_xls_results(self, path_to_file):
        u"""в UPLOAD_ROOT создаётся файл с именем file_name в котором строки с ошибками красные"""
        rb = self.format_doc.document
        rb_sheet = rb.sheet_by_index(0)
        wb = copy(rb)
        ws = wb.get_sheet(0)
        styles = get_xlwt_style_list(rb)
        for error in self.errors:
            row = rb_sheet.row(error.row_index)
            style = xlwt.easyxf('pattern: pattern solid, fore_colour orange; align: horiz centre, vert centre; borders: top thin, bottom thin, left thin, right thin;')
            for i, cell in enumerate(row):
                style.num_format_str = styles[cell.xf_index].num_format_str
                ws.write(error.row_index, i, cell.value, style)
        wb.save(path_to_file)

IMPORT_INITIAL = 0
IMPORT_START = 1
IMPORT_FINISH = 2
IMPORT_ERROR = 3
IMPORT_FINISHED_WITH_ERRORS = 4

IMPORT_TASK_CHOICES = (
    (IMPORT_INITIAL, u"Обработка не начата"),
    (IMPORT_START, u"Обработка начата"),
    (IMPORT_FINISH, u"Обработка завершена"),
    (IMPORT_FINISHED_WITH_ERRORS, u"Обработка завершена, были найдены ошибки"),
    (IMPORT_ERROR, u"Ошибка во время обработки"),
)


secure_static_storage = HexFileSystemStorage(
    location=settings.SECURE_STATIC_ROOT, base_url='/adm/administrator/importtask/')


class ImportTask(models.Model):

    class Meta:
        verbose_name = u'Файл с данными'
        verbose_name_plural = u'Файлы с данными'

    source_file = models.FileField(verbose_name=u'Файл с данными(в формате xls)',
        storage=secure_static_storage, upload_to=settings.IMPORT_STATIC_DIR)
    status = models.IntegerField(verbose_name=u"Статус", choices=IMPORT_TASK_CHOICES,
                                default=0)
    errors = models.IntegerField(verbose_name=u'Количество ошибок',
        default=IMPORT_INITIAL)
    total = models.IntegerField(verbose_name=u'Количество записей', default=0)
    fake = models.BooleanField(verbose_name=u'Только проверка файла', default=True)
    data_format = models.CharField(verbose_name=u'Модуль импорта',
        choices=INSTALLED_FORMATS, max_length=250)
    result_file = models.FileField(verbose_name=u'Результат обработки',
        storage=secure_static_storage, upload_to=settings.IMPORT_STATIC_DIR,
        blank=True, null=True)
    file_with_errors = models.FileField(verbose_name=u'Список ошибок',
        storage=secure_static_storage, upload_to=settings.IMPORT_STATIC_DIR,
        blank=True, null=True)

    def delete_files(self, *args, **kwds):
        # Try to delete result file
        def try_delete_file(file_path):
            try:
                os.remove(file_path)
            except IOError:
                pass
        if self.source_file and os.path.exists(self.source_file.path):
            try_delete_file(self.source_file.path)
        if self.result_file and os.path.exists(self.result_file.path):
            try_delete_file(self.result_file.path)
        if self.file_with_errors and os.path.exists(self.file_with_errors.path):
            try_delete_file(self.file_with_errors.path)

    def save_file_with_errors(self, context):
        new_filename, ext = os.path.splitext(os.path.basename(
                self.source_file.path))
        self.file_with_errors.name = os.path.join(
            self.file_with_errors.field.upload_to, new_filename + u'.html')
        file_with_errors = file(self.file_with_errors.path, "wb")
#        CreatePDF(render_to_string('administrator/import_errors.html',
#            context), file_with_errors)
        file_with_errors.write(render_to_string('administrator/import_errors.html',
            context).encode('utf-8'))
        file_with_errors.close()
        self.save()

    def process(self):
        # avoid cross-import
        FormatClass = importpath(self.data_format)
        source_file = open(self.source_file.path, 'r')
        descriptor, name = tempfile.mkstemp()
        os.fdopen(descriptor, 'wb').write(source_file.read())
        try:
            doc = xlrd.open_workbook(name, formatting_info=True)
        except xlrd.biffh.XLRDError:
            self.save_file_with_errors(
                {'error_message': u"Неверный тип файла. Для импорта необходимо использовать файлы формата xls",
                 'media_root': settings.MEDIA_ROOT})
            self.errors = 1
            self.status = IMPORT_FINISHED_WITH_ERRORS
            self.save()
        else:
            format_doc = FormatClass(doc)
            if format_doc.sheet.ncols >= len(format_doc.cells):
                if self.data_format in SADIKS_FORMATS:
                    logic = SadikLogic(format_doc, None, self.fake)
                else:
                    logic = RequestionLogic(format_doc, self.fake)
                logger = getLogger('django.request')
                with transaction.commit_manually():
                    try:
                        logic.validate()
                        if logic.errors:
                            transaction.rollback()
                        else:
                            transaction.commit()
                    except:
                        transaction.rollback()
                        logger.error('Import error', exc_info=sys.exc_info(),)
                        self.status = IMPORT_ERROR
                        self.save()
                        transaction.commit()
                        return logic
                new_filename, ext = os.path.splitext(os.path.basename(
                    self.source_file.path))

                if not os.path.exists(os.path.join(settings.SECURE_STATIC_ROOT, self.file_with_errors.field.upload_to)):
                    os.mkdir(os.path.join(settings.SECURE_STATIC_ROOT, self.file_with_errors.field.upload_to))

                self.result_file.name = os.path.join(self.file_with_errors.field.upload_to,
                    new_filename + '_res' + ext)

                logic.save_xls_results(self.result_file.path)

                self.save_file_with_errors(
                    {'logic': logic, 'media_root': settings.MEDIA_ROOT})


                self.total = logic.format_doc.sheet.nrows - logic.format_doc.start_line
                self.errors = len(logic.errors)
                if self.errors:
                    self.status = IMPORT_FINISHED_WITH_ERRORS
                else:
                    self.status = IMPORT_FINISH
                self.save()
                return logic
            else:
                self.save_file_with_errors(
                    {'error_message': u"Недостаточное количество столбцов",
                        'media_root': settings.MEDIA_ROOT})
                self.errors = 1
                self.status = IMPORT_FINISHED_WITH_ERRORS
                self.save()

    def __unicode__(self):
        return u'Файл с данными %s' % self.get_data_format_display()
