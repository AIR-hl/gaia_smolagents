import os
import time
import requests
import json
import math
from typing import Dict, List, Optional, Any
from urllib.parse import quote, urljoin
import re
from datetime import datetime
from smolagents import Tool


def _build_headers(ua_suffix: str) -> Dict[str, str]:
    headers = {
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": f"GitHub-{ua_suffix}-Tool (+https://github.com)",
    }
    headers["Authorization"] = f"token {os.getenv('GITHUB_API_TOKEN')}"
    return headers


def _handle_rate_limit(resp: requests.Response) -> None:
    """命中速率限制时抛出友好异常。"""
    if resp.status_code == 403 and "X-RateLimit-Remaining" in resp.headers:
        reset_ts = int(resp.headers.get("X-RateLimit-Reset", 0))
        reset_time = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(reset_ts))
        raise RuntimeError(f"GitHub API rate limit exceeded, will reset at {reset_time}")


class GitHubRepoSearchTool(Tool):
    name = "github_search_tool"
    description = (
        "Search for GitHub repositories with advanced filtering and pagination.\n"
        "The output is a dictionary with the following fields: total_count, current_page, total_pages, results[].\n"
    )

    inputs = {
        "query": {"type": "string", "description": "Search keywords."},
        "per_page": {
            "type": "integer",
            "description": "Number of results per page (1-100). Default is 10.",
            "nullable": True,
        },
        "page": {
            "type": "integer",
            "description": "Page number to retrieve. Default is 1.",
            "nullable": True,
        },
        "language": {
            "type": "string",
            "description": "Filter by programming language, e.g., 'python', 'go'.",
            "nullable": True,
        },
    }

    output_type = "any"

    def __init__(self):
        super().__init__()
        self.base_url = "https://api.github.com"
        self.headers: Dict[str, str] = _build_headers("Repo-Search")

    def forward(
        self,
        query: str,
        language: Optional[str] = None,
        per_page: int = 10,
        page: Optional[int] = None,
    ) -> Dict[str, Any]:
        per_page = max(1, min(per_page, 100))
        page = page or 1

        search_query = query.strip()
        if language:
            search_query += f" language:{language}"

        try:
            # First, get total count to calculate total pages
            count_params = {"q": search_query, "per_page": 1, "page": 1}
            count_resp = requests.get(
                f"{self.base_url}/search/repositories",
                headers=self.headers,
                params=count_params,
                timeout=30,
            )
            _handle_rate_limit(count_resp)
            count_resp.raise_for_status()
            count_data = count_resp.json()
            total_count = count_data.get("total_count", 0)

            # GitHub API for search is limited to 1000 results.
            total_pages = math.ceil(min(total_count, 1000) / per_page) if total_count > 0 else 0
            target_page = max(1, min(page, total_pages)) if total_pages > 0 else 1

            if total_count == 0:
                items = []
            else:
                params = {"q": search_query, "per_page": per_page, "page": target_page}
                resp = requests.get(
                    f"{self.base_url}/search/repositories",
                    headers=self.headers,
                    params=params,
                    timeout=30,
                )
                _handle_rate_limit(resp)
                resp.raise_for_status()
                data = resp.json()
                items = data.get("items", [])

            return {
                "total_count": total_count,
                "current_page": target_page,
                "total_pages": total_pages,
                "results": [
                    {
                        "full_name": r["full_name"],
                        "description": r.get("description") or "",
                        "url": r["html_url"],
                        "updated_at": r["updated_at"],
                        "created_at": r["created_at"],
                        "stars": r["stargazers_count"],
                        "language": r.get("language"),
                    }
                    for r in items
                ],
            }
        except requests.RequestException as e:
            raise RuntimeError(f"GitHub search failed: {e}") from e


class GitHubIssueSearchTool(Tool):
    """Search for GitHub issues with advanced filtering."""

    name = "github_issue_search"
    description = (
        "Search for GitHub issues with advanced filtering.\n"
        "The output is a dictionary with the following fields: total_count, current_page, total_pages, results[].\n"
    )

    inputs = {
        "query": {"type": "string", "description": "Search keywords."},
        "repo": {"type": "string", "description": "The repository to search in (e.g., 'owner/repo')."},
        "state": {
            "type": "string",
            "description": "Filter by issue state ('open', 'closed', or 'all').",
            "nullable": True,
        },
        "per_page": {
            "type": "integer",
            "description": "Number of results per page (1-100). Default is 10.",
            "nullable": True,
        },
        "page": {
            "type": "integer",
            "description": "Page number to retrieve. Default is 1.",
            "nullable": True
        },
        "labels": {"type": "array", "description": "Filter by issue labels.", "nullable": True},
        "author": {"type": "string", "description": "Filter by issue author.", "nullable": True},
    }

    output_type = "any"

    def __init__(self):
        super().__init__()
        self.base_url = "https://api.github.com"
        self.headers = _build_headers("Issue-Search")

    def forward(
        self,
        query: str,
        repo: str,
        state: str = "all",
        author: Optional[str] = None,
        per_page: int = 10,
        page: Optional[int] = None,
        labels: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        per_page = max(1, min(per_page, 100))
        page = page or 1

        search_q = f"{query} type:issue"
        if repo:
            search_q += f" repo:{repo}"
        if state != "all":
            search_q += f" state:{state}"
        if author:
            search_q += f" author:{author}"
        if labels:
            for label in labels:
                # 用双引号包裹 label，转义内部引号
                safe_label = label.replace('"', '\"')
                search_q += f' label:"{safe_label}"'
        try:
            # First, get total count to calculate total pages
            count_params = {"q": search_q, "per_page": 1, "page": 1}
            count_resp = requests.get(
                f"{self.base_url}/search/issues",
                headers=self.headers,
                params=count_params,
                timeout=30,
            )
            _handle_rate_limit(count_resp)
            count_resp.raise_for_status()
            count_data = count_resp.json()
            total_count = count_data.get("total_count", 0)
            
            total_pages = math.ceil(min(total_count, 1000) / per_page) if total_count > 0 else 0
            target_page = max(1, min(page, total_pages)) if total_pages > 0 else 1

            if total_count == 0:
                items = []
            else:
                params = {"q": search_q, "per_page": per_page, "page": target_page}
                resp = requests.get(
                    f"{self.base_url}/search/issues",
                    headers=self.headers,
                    params=params,
                    timeout=30,
                )
                _handle_rate_limit(resp)
                resp.raise_for_status()
                data = resp.json()
                items = data.get("items", [])

            results = [
                {
                    "number": it["number"],
                    "title": it["title"],
                    "url": it["html_url"],
                    "state": it["state"],
                    "labels": [label["name"] for label in it["labels"]] if it["labels"] else [],
                    "author": it["user"]["login"],
                    "created_at": it["created_at"],
                    "updated_at": it["updated_at"],
                    "comments": it["comments"],
                }
                for it in items
            ]
            return {"total_count": total_count, "current_page": target_page, "total_pages": total_pages, "results": results}
        except requests.RequestException as exc:
            raise RuntimeError(f"Issue search failed: {exc}") from exc


class GitHubPullRequestSearchTool(Tool):
    """Search for GitHub pull requests with advanced filtering."""

    name = "github_pr_search"
    description = (
        "Search for GitHub pull requests with advanced filtering.\n"
        "The output is a dictionary with the following fields: total_count, current_page, total_pages, results[].\n"
    )

    inputs = {
        "query": {"type": "string", "description": "Search keywords."},
        "repo": {
            "type": "string",
            "description": "The repository to search in (e.g., 'owner/repo').",
            "nullable": True,
        },
        "per_page": {
            "type": "integer",
            "description": "Number of results per page (1-100). Default is 10.",
            "nullable": True,
        },
        "page": {
            "type": "integer",
            "description": "Page number to retrieve. Default is 1.",
            "nullable": True
        },
        "state": {
            "type": "string",
            "description": "Filter by pull request state ('open', 'closed', 'merged', or 'all').",
            "nullable": True,
        },
        "author": {"type": "string", "description": "Filter by pull request author.", "nullable": True},

    }

    output_type = "any"

    def __init__(self):
        super().__init__()
        self.base_url = "https://api.github.com"
        self.headers = _build_headers("PR-Search")

    def forward(
        self,
        query: str,
        repo: Optional[str] = None,
        state: str = "all",
        author: Optional[str] = None,
        per_page: int = 10,
        page: Optional[int] = None
    ) -> Dict[str, Any]:
        per_page = max(1, min(per_page, 100))
        page = page or 1

        search_q = f"{query} type:pr"
        if repo:
            search_q += f" repo:{repo}"
        if state != "all":
            search_q += " is:merged" if state == "merged" else f" state:{state}"
        if author:
            search_q += f" author:{author}"

        try:
            # First, get total count to calculate total pages
            count_params = {"q": search_q, "per_page": 1, "page": 1}
            count_resp = requests.get(
                f"{self.base_url}/search/issues",
                headers=self.headers,
                params=count_params,
                timeout=30,
            )
            _handle_rate_limit(count_resp)
            count_resp.raise_for_status()
            count_data = count_resp.json()
            total_count = count_data.get("total_count", 0)

            total_pages = math.ceil(min(total_count, 1000) / per_page) if total_count > 0 else 0
            target_page = max(1, min(page, total_pages)) if total_pages > 0 else 1

            if total_count == 0:
                items = []
            else:
                params = {"q": search_q, "per_page": per_page, "page": target_page}
                resp = requests.get(
                    f"{self.base_url}/search/issues",
                    headers=self.headers,
                    params=params,
                    timeout=30,
                )
                _handle_rate_limit(resp)
                resp.raise_for_status()
                data = resp.json()
                items = data.get("items", [])

            results = [
                {
                    "number": it["number"],
                    "title": it["title"],
                    "url": it["html_url"],
                    "state": it["state"],
                    "author": it["user"]["login"],
                    "created_at": it["created_at"],
                    "updated_at": it["updated_at"],
                    "comments": it["comments"],
                    "repo_full_name": it["repository_url"].rsplit("/", 2)[-2:]
                    if "repository_url" in it
                    else None,
                }
                for it in items
            ]
            return {"total_count": total_count, "current_page": target_page, "total_pages": total_pages, "results": results}
        except requests.RequestException as exc:
            raise RuntimeError(f"Pull Request search failed: {exc}") from exc


class GitHubReleaseSearchTool(Tool):
    """List releases for a repository or get a specific release by tag."""

    name = "github_release_view"
    description = (
        "List releases for a repository or get a specific release by tag.\n"
        "The output is a dictionary with the following fields: current_page, total_pages, releases[].\n"
    )

    inputs = {
        "repo": {"type": "string", "description": "The repository to view releases for (e.g., 'owner/repo')."},
        "tag": {
            "type": "string",
            "description": "Get a specific release by tag name.",
            "nullable": True,
        },
        "per_page": {
            "type": "integer",
            "description": "Number of results per page (1-100). Default is 10.",
            "nullable": True,
        },
        "page": {
            "type": "integer",
            "description": "Page number to retrieve. Default is 1.",
            "nullable": True
        }
    }

    output_type = "any"

    def __init__(self):
        super().__init__()
        self.base_url = "https://api.github.com"
        self.headers = _build_headers("Release-View")

    def forward(self, repo: str, per_page: int = 10, page: Optional[int] = None, tag: Optional[str] = None ) -> Dict[str, Any]:
        if tag:
            try:
                resp = requests.get(
                    f"{self.base_url}/repos/{repo}/releases/tags/{tag}",
                    headers=self.headers,
                    timeout=30,
                )
                _handle_rate_limit(resp)
                if resp.status_code == 404:
                    return {"current_page": 0, "total_pages": 0, "releases": []}

                resp.raise_for_status()
                r = resp.json()

                results = [
                    {
                        "tag_name": r["tag_name"],
                        "description": r.get("name", ""),
                        "url": r["html_url"],
                        "created_at": r["created_at"],
                        "published_at": r["published_at"],
                        "author": r["author"]["login"],
                    }
                ]
                return {"current_page": 1, "total_pages": 1, "releases": results}
            except requests.RequestException as exc:
                raise RuntimeError(f"Failed to get release by tag '{tag}': {exc}") from exc

        per_page = max(1, min(per_page, 100))
        page = page or 1

        try:
            # HEAD request to get total item count from Link header with per_page=1
            head_resp = requests.head(
                f"{self.base_url}/repos/{repo}/releases",
                headers=self.headers,
                params={"per_page": 1, "page": 1},
                timeout=10,
            )
            _handle_rate_limit(head_resp)
            head_resp.raise_for_status()

            link_header = head_resp.headers.get("Link")
            total_pages = 1
            if link_header:
                match = re.search(r'page=(\d+)>; rel="last"', link_header)
                if match:
                    total_items = int(match.group(1))
                    total_pages = math.ceil(total_items / per_page)
            
            target_page = max(1, min(page, total_pages)) if total_pages > 0 else 1

            resp = requests.get(
                f"{self.base_url}/repos/{repo}/releases",
                headers=self.headers,
                params={"per_page": per_page, "page": target_page},
                timeout=30,
            )
            _handle_rate_limit(resp)
            resp.raise_for_status()
            data = resp.json()

            results = [
                {
                    "tag_name": r["tag_name"],
                    "description": r.get("name", ""),
                    "url": r["html_url"],
                    "created_at": r["created_at"],
                    "published_at": r["published_at"],
                    "author": r["author"]["login"],
                }
                for r in data
            ]
            return {"current_page": target_page, "total_pages": total_pages, "releases": results}
        except requests.RequestException as exc:
            raise RuntimeError(f"Release query failed: {exc}") from exc


# 使用示例
if __name__ == "__main__":
    # 创建工具实例
    os.environ["GITHUB_API_TOKEN"] = "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"
    repo_search = GitHubRepoSearchTool()
    issue_search = GitHubIssueSearchTool()
    pr_search = GitHubPullRequestSearchTool()
    release_view = GitHubReleaseSearchTool()
    
    # 使用示例
    # print("=== 搜索Python机器学习相关仓库 ===")
    # repos = repo_search.forward("machine learning", language="python", page=10000)
    # print(json.dumps(repos, indent=2, ensure_ascii=False))
    
    print("\n=== 搜索Issues ===")
    issues = issue_search.forward("gpu", repo="pytorch/pytorch", labels=["needs reproduction"], state="open", per_page=100)
    print(json.dumps(issues, indent=2, ensure_ascii=False))
    
    # print("\n=== 查看Release ===")
    # releases = release_view.forward("pytorch/pytorch", page=4)
    # print(json.dumps(releases, indent=2, ensure_ascii=False))

    # print("\n=== 通过Tag查看Release ===")
    # release = release_view.forward("pytorch/pytorch", tag="v2.1.0")
    # print(json.dumps(release, indent=2, ensure_ascii=False))