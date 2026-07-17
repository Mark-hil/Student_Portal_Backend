"""Pagination classes."""
from rest_framework.pagination import PageNumberPagination, CursorPagination as DRFCursor
from rest_framework.response import Response


class StandardResultsPagination(PageNumberPagination):
    page_size              = 25
    page_size_query_param  = "page_size"
    max_page_size          = 100

    def get_paginated_response(self, data):
        return Response({
            "count":        self.page.paginator.count,
            "next":         self.get_next_link(),
            "previous":     self.get_previous_link(),
            "total_pages":  self.page.paginator.num_pages,
            "current_page": self.page.number,
            "results":      data,
        })


class CursorPagination(DRFCursor):
    """Use for very large tables — no slow COUNT(*)."""
    page_size            = 25
    ordering             = "-created_at"
    cursor_query_param   = "cursor"
