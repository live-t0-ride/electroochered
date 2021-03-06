$(document).ready(function () {
    // прячем select со всем ТО, в дальнейшем модифицируем его средствами
    // jQuery, не показывая пользователю, и отправляем при подтверждении формы
    $('#id_areas').hide();
});

// центрируем карту по ТО
function center_area(id) {
    areas_all.forEach(function (area) {
        if (area.id == id) {
            try {
                map.setView([area.center[1], area.center[0]], 13);
            } catch (err) {
                console.log(err);
            }
        }
    });
}

// центрируем карту по садику
function center_to_kidgdn(elem) {
    for (sadik in sadik_location_data) {
        var s = sadik_location_data[sadik];
        if (s.id == elem.id) {
            try {
                map.setView([s.location[1], s.location[0]], 15);
                // после центрирования, показываем popup
                for (key in sadik_markers) {
                    if (key == s.id) {
                        sadik_markers[key].openPopup();
                    }
                }
            } catch (err) {
                console.log(err);
            }
        }
    }
}


function delete_special_benefits() {
    slct = $('#bsmSelectbsmContainer0 option');
    slct.each(function() {
        if (this.text.indexOf('Электроочереди') > -1) {
            this.remove();
        }
    });
}

// условный центр списка садиков
function get_center(sadik_list) {
    return sadik_list.reduce(getAverageCoords, {location: [0, 0]});
}

// добавляем выбранную ТО к areas
$(document).on("change", ".areas_all", function () {
    var id = $(this).val();
    // собственно само добавление
    $('#id_areas option').each(function () {
        if (this.value == id) {
            this.selected = true;
            areas_ids.push(parseInt(id));
            renderMarkers(sadik_location_data, map);
        }
    });
    // центрируем карту по ТО
    try {
        center_area(id);
    } catch (err) {
        console.log(err);
    }

    // создаем и отображаем новое поле с выбранной ТО
    var text = $(this).children(":selected").text();
    add_area_field($(this), id, text);

    // помечаем блок измененным
    var container_el = $(this).parents('.field');
    field_changed(container_el);
    // удаляем поле select
    $(this).remove();
});

function add_area_field(element, id, text) {
    $(element).before(' \
    <p class="field-value hidden-input"> \
        <a id="area_map_anchor" class="icon-map-marker" href="#" onclick="center_area(' + id + '); return false"></a> \
        <a id="' + id + '" class="value value-anchor" href="#" onclick="show_kidgardens(this); return false">' + text + '</a> \
        <span class="caret caret-right caret-margins"></span> \
        <a class="editor" href="#" onclick="del_field(this); return false" data-toggle="tooltip" title="Удалить группу ДОУ"> \
        <i id="area-close" class="icon-remove"></i></a> \
    </p> \
    <ul class="kidgs_list unstyled"></ul>');
}

// По клику на ссылку выводим еще один select с ТО
function add_area(element) {
    $(element).before(' \
    <select class="areas_all"> \
        {% for area in areas_all %} \
            <option value="{{ area.id }}">{{ area }}</option> \
        {% endfor %} \
    </select>');
}


function getAverageCoords(prev, curr, ind, arr) {
    if (arr.length == 1) {
        return arr[0].location;
    }
    if (ind < (arr.length - 1)) {
        return { location: [ prev.location[0] + curr.location[0],
                 prev.location[1] + curr.location[1] ] }
    }
    else {
        return [ (prev.location[0] + curr.location[0]) / arr.length,
                 (prev.location[1] + curr.location[1]) / arr.length ]
    }
}

// показываем детские сады под ТО
function show_kidgardens(elem) {
    var ul = $(elem).parent().next();
    var items = $(elem).parent().next().children()
    if (items.length <=0) {
        $(elem).next().removeClass("caret-right");
        for (s in sadik_location_data) {
            var sadik = sadik_location_data[s];
            if (elem.id == sadik.area_id) {
                var li = $('<li/>')
                    .text(sadik.name)
                    .appendTo(ul);
                var a = $('<a/>')
                    .attr('onclick', 'center_to_kidgdn(this); return false')
                    .attr('id', sadik.id)
                    .attr('href', '#')
                    .prependTo(li);
                var img = $('<img/>')
                    .attr('src', '/static/img/sadik-icon-gray.png')
                    .attr('height', '11')
                    .attr('width', '11')
                    .prependTo(a);
                if (areas_ids) {
                    img.attr('src', '/static/img/sadik-icon-yellow.png')
                }
                if (pref_sadiks_ids.indexOf(sadik.id) >= 0){
                    img.attr('src', '/static/img/sadik-icon.png')
                }
            }
        };
    }
    else {
        items.remove();
        $(elem).next().addClass("caret-right");
    }
}

// удаление ТО пользователем по нажатию на кнопку 'X'
function del_field(element) {
    var parent = $(element.parentElement);
    var id = parent.children('a').next().attr('id');
    $('#id_areas option').each(function() {
        if (this.value==id) {
            this.selected = false;
            var index = areas_ids.indexOf(parseInt(id));
            areas_ids.splice(index, 1);
            renderMarkers(sadik_location_data, map)
        };
    });
    $(parent).next().remove();
    $(parent).remove();
}


//отрисовка садиков на карте
function renderMarkers(markers, map) {
    sadik_markers = {}
    if (sadiksLayer){
        map.removeLayer(sadiksLayer)
    }
    if (prefSadikLayer){
        map.removeLayer(prefSadikLayer)
    }
    if (areaSadiksLayer){
        map.removeLayer(areaSadiksLayer)
    }
    sadiksLayer = new L.MarkerClusterGroup({
        iconCreateFunction: function(childCount) {
            return new L.DivIcon({ html: '<div><span>' + childCount + '</span></div>', className: 'marker-cluster marker-cluster-gray', iconSize: new L.Point(40, 40) });
        },
        maxClusterRadius: 30
    });
    areaSadiksLayer = new L.MarkerClusterGroup({
        iconCreateFunction: function(childCount) {
            return new L.DivIcon({ html: '<div><span>' + childCount + '</span></div>', className: 'marker-cluster marker-cluster-medium', iconSize: new L.Point(40, 40) });
        },
        maxClusterRadius: 30
    });
    prefSadikLayer = new L.LayerGroup()
    var activeSadikIcon = L.icon({
        iconUrl: activeSadikIconURL,

        iconSize:     [22, 23], // size of the icon
        iconAnchor:   [11, 11], // point of the icon which will correspond to marker's location
        shadowAnchor: [4, 62]  // the same for the shadow
    });
    var areaSadikIcon = L.icon({
        iconUrl: areaSadikIconURL,

        iconSize:     [22, 23], // size of the icon
        iconAnchor:   [11, 11], // point of the icon which will correspond to marker's location
        shadowAnchor: [4, 62]  // the same for the shadow
    });
    var inactiveSadikIcon = L.icon({
        iconUrl: inactiveSadikIconURL,

        iconSize:     [22, 23], // size of the icon
        iconAnchor:   [11, 11], // point of the icon which will correspond to marker's location
        shadowAnchor: [4, 62]  // the same for the shadow
    });
    function bind_popup(marker){
        marker.bindPopup('<b>'+markers[key].name+'</b><div>Адрес: '+markers[key].address+'</div><div>Телефон: '+ markers[key].phone +'</div><a href="'+ markers[key].url +'">Перейти к ДОУ</a>');
    }
    for (var key in markers) {
        if (jQuery.inArray(markers[key].id, pref_sadiks_ids) != -1){
            var m = L.marker(markers[key].location.slice().reverse(),
                    {title: markers[key].name, icon: activeSadikIcon, zIndexOffset: 1000});
            m.bindPopup('<b>'+markers[key].name+'</b><div>Адрес: '+markers[key].address+'</div><div>Телефон: '+ markers[key].phone +'</div><a href="'+ markers[key].url +'">Перейти к ДОУ</a>');
            prefSadikLayer.addLayer(m)
            sadik_markers[markers[key].id] = m;
        } else {
            if ((areas_ids !== null && areas_ids.length == 0) || jQuery.inArray(markers[key].area_id, areas_ids) != -1){
                var m = L.marker(markers[key].location.slice().reverse(), {title: markers[key].name, icon: areaSadikIcon});
                areaSadiksLayer.addLayer(m);
            } else {
                var m = L.marker(markers[key].location.slice().reverse(), {title: markers[key].name, icon: inactiveSadikIcon});
                sadiksLayer.addLayer(m);
            }
        bind_popup(m)
        }
        sadik_markers[markers[key].id] = m;
    }
    map.addLayer(areaSadiksLayer, true);
    map.addLayer(sadiksLayer, true);
    map.addLayer(prefSadikLayer)
}



var requestion = (function() {
    var funcs = {};

    // получаем примерные координаты исходя из адреса
    function get_coords(url) {
        $.ajax(url, {
            type: 'GET',
            data: {'address': $('#address_text').val()},
            dataType:'json',
            success: function(data, textStatus, jqXHR){
                $('#coords_alert').hide();
                $('#coords_success').hide();
                if (data.ok) {
                    $('#coords_success').show();
                    map.setView([data.coords[1], data.coords[0]], 17);
                } else {
                    $('#coords_alert').text('Координаты по вашему запросу не найдены. ' +
                                            'Попробуйте изменить адрес.');
                    $('#coords_alert').show();
                }
            },
            error: function(){
                $('#coords_alert').addClass('alert-error');
                $('#coords_alert').text('Ошибка обработки запроса. Попробуйте еще раз или ' +
                                        'установите маркер на карте самостоятельно.');
                $('#coords_alert').show();
            }
        });
    }
    funcs.get_coords = get_coords;

    return funcs;
}());