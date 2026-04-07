"Info page."
from trame.widgets import vuetify3 as vuetify

def render_info():
    "Info page layout."
    text_classes = 'pa-0 ma-0'
    text_style = "font-size: 16px;"

    with vuetify.VCard(classes="pl-5 pt-2", variant='flat'):
        vuetify.VCardTitle("Description of the reservoir model",
            classes=text_classes)
        vuetify.VCardText('Dimensions: ' + '{{dimens}}',
            classes=text_classes, style=text_style)
        vuetify.VCardText('Fluids: ' + '{{fluids}}',
            classes=text_classes, style=text_style)
        vuetify.VCardText('Total cells: ' + '{{total_cells}}',
            classes=text_classes, style=text_style)
        vuetify.VCardText('Active cells: ' + '{{active_cells}}',
            classes=text_classes, style=text_style)
        vuetify.VCardText('Pore volume: ' + "{{pore_vol}}" + ' ' + "{{units3}}",
            classes=text_classes, style=text_style)
        vuetify.VCardText('Oil volume: ' + "{{oil_vol}}" + ' ' + "{{units3}}",
            classes=text_classes, style=text_style)
        vuetify.VCardText('Water volume: ' + "{{wat_vol}}" + ' ' + "{{units3}}",
            classes=text_classes, style=text_style)
        vuetify.VCardText('Gas volume: ' + "{{gas_vol}}" + ' ' + "{{units4}}",
            classes=text_classes, style=text_style)
        vuetify.VCardText('Start date: ' + '{{startDate}}',
            classes=text_classes, style=text_style)
        vuetify.VCardText('Last date: ' + '{{lastDate}}',
            classes=text_classes, style=text_style)
        vuetify.VCardText('Number of timesteps: ' + '{{max_timestep}}',
            classes=text_classes, style=text_style)
        vuetify.VCardText('Number of wells: ' + '{{num_wells}}',
            classes=text_classes, style=text_style)
        vuetify.VCardText('Total oil production: ' + '{{total_oil_production}}' + ' ' + "{{units1}}",
            classes=text_classes, style=text_style)
        vuetify.VCardText('Total water production: ' + '{{total_wat_production}}' + ' ' + "{{units1}}",
            classes=text_classes, style=text_style)
        vuetify.VCardText('Total gas production: ' + '{{total_gas_production}}' + ' ' + "{{units2}}",
            classes=text_classes, style=text_style)

        vuetify.VCardTitle("Components and attributes",
            classes='pa-0 ma-0')
        vuetify.VCardText("Attributes of grid: " + "{{components_attrs['grid']}}",
            classes=text_classes, style=text_style)
        vuetify.VCardText("Attributes of rock: " + "{{components_attrs['rock']}}",
            classes=text_classes, style=text_style)
        vuetify.VCardText("Attributes of states: " + "{{components_attrs['states']}}",
            classes=text_classes, style=text_style)
        vuetify.VCardText("Attributes of tables: " + "{{components_attrs['tables']}}",
            classes=text_classes, style=text_style)
        vuetify.VCardText("Attributes of wells: " + "{{components_attrs['wells']}}",
            classes=text_classes, style=text_style)
        vuetify.VCardText("Attributes of faults: " + "{{components_attrs['faults']}}",
            classes=text_classes, style=text_style)
