from django import forms


from organizations.models import Organization


class CategoryQuestionsUploadForm(forms.Form):
    organization = forms.ModelChoiceField(
        label="Organization",
        queryset=Organization.objects.filter(
            status="active"
        ).order_by("name"),
        empty_label="Select an organization",
    )

    excel_file = forms.FileField(
        label="Category Questions Excel File",
        help_text=(
            "Upload an .xlsx file containing service categories "
            "and customer questions."
        ),
        widget=forms.ClearableFileInput(
            attrs={
                "accept": ".xlsx",
            }
        ),
    )

    def clean_excel_file(self):
        excel_file = self.cleaned_data["excel_file"]

        filename = excel_file.name.lower()

        if not filename.endswith(".xlsx"):
            raise forms.ValidationError(
                "Please upload an Excel .xlsx file."
            )

        # 10 MB maximum
        max_size = 10 * 1024 * 1024

        if excel_file.size > max_size:
            raise forms.ValidationError(
                "The Excel file must be smaller than 10 MB."
            )

        return excel_file