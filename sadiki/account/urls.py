# -*- coding: utf-8 -*-
from django.conf import settings
from django.conf.urls.defaults import patterns, url
from sadiki.account.views import RequestionAdd, RequestionChange, \
    BenefitsChange, PreferredSadiksChange, AccountFrontPage, RequestionInfo, \
    DocumentsChange, BenefitCategoryChange, GenerateBlank

if settings.FACILITY_STORE == settings.FACILITY_STORE_YES:
    change_benefits_view = BenefitsChange.as_view()
else:
    change_benefits_view = BenefitCategoryChange.as_view()

urlpatterns = patterns('',
    url(r'^$', AccountFrontPage.as_view(), name='account_frontpage'),
    url(r'^request/add/$', RequestionAdd.as_view(),
        name=u'requestion_add_by_user'),
    url(r'^request/(?P<requestion_id>\d{1,7})/$',
        RequestionInfo.as_view(), name=u'account_requestion_info'),
    url(r'^request/(?P<requestion_id>\d{1,7})/generate_blank/$',
        GenerateBlank.as_view(), name='account_generate_blank'),
)
