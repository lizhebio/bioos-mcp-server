"""Dockstore Workflow Search and Download Tool

This tool provides two main functionalities:
1. Search for workflows on Dockstore
2. Download WDL files from specified workflows

Features:
- Support complex multi-field searches
- Support AND/OR boolean operations
- Support wildcard matching
- Support full sentence search
- Sort results by relevance
- Filter by descriptor type, verification status and more
- Automatic file downloads

Searchable Fields:
- full_workflow_path: Complete workflow path
- description: Workflow description
- name: Workflow name
- workflowName: Workflow display name
- organization: Organization name
- all_authors.name: Author names
- labels.value: Workflow labels
- categories.name: Workflow categories
- workflowVersions.sourceFiles.content: Workflow source file content
- input_file_formats.value: Input file formats
- output_file_formats.value: Output file formats

Usage Examples:
1. Basic search for workflows about RNA sequencing:
   python dockstore_search.py -q "RNA-seq" "description" "AND"

2. Search for WDL workflows for variant calling:
   python dockstore_search.py -q "variant calling" "description" "AND" --descriptor-type "WDL"

3. Search for verified workflows for cancer analysis:
   python dockstore_search.py -q "cancer" "description" "AND" --verified-only

4. Multi-field search with different criteria:
   python dockstore_search.py -q "Broad Institute" "organization" "AND" -q "WDL" "descriptorType" "AND"

5. Search with wildcard matching:
   python dockstore_search.py -q "genom*" "description" "OR" --type wildcard

6. Search for workflows by author:
   python dockstore_search.py -q "John Smith" "all_authors.name" "AND"

7. Search for workflows with specific input format:
   python dockstore_search.py -q "BAM" "input_file_formats.value" "AND"

8. Search for workflows with specific output format:
   python dockstore_search.py -q "VCF" "output_file_formats.value" "AND"

9. Search for workflows with full detail output:
   python dockstore_search.py -q "exome" "description" "AND" --outputfull

10. Search for specific workflow by path:
    python dockstore_search.py -q "github.com/broadinstitute/gatk/Mutect2" "full_workflow_path" "AND"

11. Search for workflows in specific category:
    python dockstore_search.py -q "Genomics" "categories.name" "AND"

12. Search for both active and archived workflows:
    python dockstore_search.py -q "legacy" "description" "AND" --include-archived
"""

from typing import Any, Dict, List, Optional, Union
from pathlib import Path
from uuid import uuid4
import argparse
import asyncio
import httpx
import json
import os


class DockstoreSearch:
    """Dockstore search client for querying workflows using Elasticsearch."""
    
    API_BASE = "https://dockstore.org/api/api/ga4gh/v2/extended/tools/entry/_search"
    API_TOOLS = "https://dockstore.org/api/ga4gh/v2/tools"
    USER_AGENT = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    )

    def __init__(self) -> None:
        """Initialize the DockstoreSearch client."""
        self.base_url = "https://dockstore.org/api/workflows"
        self.search_url = self.API_BASE
        self.headers = {
            "accept": "application/json",
            "accept-language": "en-US,en;q=0.9",
            "content-type": "application/json",
            "origin": "https://dockstore.org",
            "priority": "u=1, i",
            "sec-ch-ua": '"Google Chrome";v="131", "Chromium";v="131", "Not_A Brand";v="24"',
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": '"Windows"',
            "sec-fetch-dest": "empty",
            "sec-fetch-mode": "cors",
            "sec-fetch-site": "same-origin",
            "user-agent": self.USER_AGENT,
            "x-dockstore-ui": "2.13.3",
            "x-request-id": str(uuid4()),
            "x-session-id": str(uuid4())
        }

    def _build_search_body(
        self, 
        queries: List[Dict[str, Union[List[str], str]]], 
        is_sentence: bool,
        query_type: str,
        descriptor_type: str = None,  # 新增：描述符类型筛选
        verified_only: bool = False,  # 新增：仅已验证
        include_archived: bool = False  # 新增：包含归档的工作流
    ) -> Dict[str, Any]:
        """Build the search request body with enhanced filtering options."""
        search_body = {
            "size": 201,
            "_source": [
                # 基本元数据
                "all_authors", "approvedAITopic", "descriptorType",
                "descriptorTypeSubclass", "full_workflow_path", "gitUrl",
                "name", "namespace", "organization", "private_access",
                "providerUrl", "repository", "starredUsers", "toolname",
                "tool_path", "topicAutomatic", "topicSelection", "verified",
                "workflowName", "description", "workflowVersions",
                # 新增字段
                "categories.name", "categories.displayName",
                "descriptor_type_versions", "engine_versions",
                "input_file_formats.value", "output_file_formats.value",
                "archived", "openData", "has_checker",
                "verified_platforms", "execution_partners", "validation_partners"
            ],
            "sort": [
                {"archived": {"order": "asc"}},
                {"_score": {"order": "desc"}}
            ],
            "highlight": {
                "type": "unified",
                "pre_tags": ["<b>"],
                "post_tags": ["</b>"],
                "fields": {
                    "full_workflow_path": {},
                    "tool_path": {},
                    "workflowVersions.sourceFiles.content": {},
                    "tags.sourceFiles.content": {},
                    "description": {},
                    "labels.value": {},  # 更新为完整字段名
                    "all_authors.name": {},
                    "topicAutomatic": {},
                    "categories.topic": {},
                    "categories.displayName": {},
                    "categories.name": {},  # 新增高亮字段
                    "input_file_formats.value": {},  # 新增高亮字段
                    "output_file_formats.value": {}  # 新增高亮字段
                }
            },
            "query": {
                "bool": {
                    "must": [{"match": {"_index": "workflows"}}],
                    "should": [],
                    "minimum_should_match": 1,
                    "filter": []  # 添加过滤条件
                }
            }
        }

        # 添加过滤条件
        if descriptor_type:
            search_body["query"]["bool"]["filter"].append(
                {"term": {"descriptorType": descriptor_type}}
            )
            
        if verified_only:
            search_body["query"]["bool"]["filter"].append(
                {"term": {"verified": True}}
            )
            
        if not include_archived:
            search_body["query"]["bool"]["filter"].append(
                {"term": {"archived": False}}
            )

        # 处理查询条件
        for query in queries:
            terms = query.get("terms", [])
            fields = query.get("fields", [])
            
            for term, field in zip(terms, fields):
                # 为搜索字段分配适当的权重
                boost_value = 1.0
                if field in ["full_workflow_path", "tool_path"]:
                    boost_value = 14.0
                elif field in ["description", "workflowName", "name"]:
                    boost_value = 10.0
                elif field in ["categories.name", "categories.displayName"]:
                    boost_value = 8.0
                elif field in ["all_authors.name", "organization"]:
                    boost_value = 6.0
                elif field in ["labels.value", "input_file_formats.value", "output_file_formats.value"]:
                    boost_value = 4.0
                else:
                    boost_value = 2.0
                
                # 构建查询语句
                if query_type == "wildcard":
                    search_body["query"]["bool"]["should"].append({
                        "wildcard": {
                            field: {
                                "value": f"*{term}*",
                                "case_insensitive": True,
                                "boost": boost_value
                            }
                        }
                    })
                else:  # match_phrase
                    match_type = "match_phrase" if is_sentence else "match"
                    search_body["query"]["bool"]["should"].append({
                        match_type: {
                            field: {
                                "query": term,
                                "boost": boost_value
                            }
                        }
                    })
        
        return search_body

    async def search(
        self, 
        queries: List[Dict[str, Union[List[str], str]]], 
        is_sentence: bool = False,
        query_type: str = "match_phrase",
        descriptor_type: str = None,  # 新增参数
        verified_only: bool = False,  # 新增参数
        include_archived: bool = False  # 新增参数
    ) -> Optional[Dict[str, Any]]:
        """Execute workflow search with enhanced filtering options."""
        try:
            print(f"开始构建搜索查询: {queries}")
            search_body = self._build_search_body(
                queries, 
                is_sentence, 
                query_type,
                descriptor_type,
                verified_only,
                include_archived
            )
            print(f"搜索体构建完成, 准备发送请求")
            
            async with httpx.AsyncClient(timeout=30.0) as client:  # 设置30秒超时
                print(f"正在发送请求到 {self.search_url}")
                response = await client.post(
                    self.search_url,
                    headers=self.headers,
                    json=search_body
                )
                print(f"请求完成, 状态码: {response.status_code}")
                
                if response.status_code != 200:
                    print(f"错误响应: {response.text}")
                    return None
                    
                return response.json()
        except httpx.TimeoutException:
            print("请求超时")
            return {"error": "Request timed out after 30 seconds"}
        except Exception as e:
            print(f"搜索过程中发生错误: {str(e)}")
            import traceback
            traceback.print_exc()
            return None

    def format_results(self, results: dict, output_full: bool = False) -> Union[str, List[str]]:
        """Format search results as a concise list of links with enhanced information."""
        if not results or "hits" not in results:
            return "No matching workflows found"
        
        formatted = ["The following workflows were found in Dockstore:\n"]
        workflows = []
        
        for hit in results["hits"].get("hits", []):
            source = hit.get("_source", {})
            score = hit.get("_score", 0)
            
            name = (source.get('workflowName') or 
                   source.get('name') or 
                   source.get('repository') or 
                   'Unnamed Workflow')
            path = source.get('full_workflow_path', '')
            desc = source.get('description', '')
            if desc:
                desc = desc.split('\n')[0]
                
            # 增强信息
            workflow_info = {
                'name': name,
                'path': path,
                'desc': desc,
                'score': score,
                'descriptor_type': source.get('descriptorType', ''),
                'categories': [cat.get('name', '') for cat in source.get('categories', [])],
                'verified': source.get('verified', False),
                'authors': [author.get('name', '') for author in source.get('all_authors', [])],
                'organization': source.get('organization', ''),
                'input_formats': [fmt.get('value', '') for fmt in source.get('input_file_formats', [])],
                'output_formats': [fmt.get('value', '') for fmt in source.get('output_file_formats', [])]
            }
            
            workflows.append(workflow_info)
        
        workflows.sort(key=lambda x: x['score'], reverse=True)
        total_results = len(workflows)
        display_count = min(total_results, 5)
        
        if total_results > 5:
            formatted.append(f"Found {total_results} workflows, showing top {display_count} by relevance:\n")
        else:
            formatted.append(f"Found {total_results} workflow(s):\n")
        
        for wf in workflows[:display_count]:
            url = f"https://dockstore.org/workflows/{wf['path']}"
            base_info = f"- [{wf['name']}]({url}) (similarity: {wf['score']:.2f})"
            
            if wf['verified']:
                base_info += " ✓"  # 添加验证标记
                
            formatted.append(base_info)
            
            # 添加描述和其他信息
            if wf['desc']:
                formatted.append(f"  {wf['desc']}")
                
            if output_full:
                if wf['descriptor_type']:
                    formatted.append(f"  Type: {wf['descriptor_type']}")
                if wf['categories']:
                    formatted.append(f"  Categories: {', '.join(wf['categories'])}")
                if wf['authors']:
                    formatted.append(f"  Authors: {', '.join(wf['authors'])}")
                if wf['organization']:
                    formatted.append(f"  Organization: {wf['organization']}")
                if wf['input_formats']:
                    formatted.append(f"  Input formats: {', '.join(wf['input_formats'])}")
                if wf['output_formats']:
                    formatted.append(f"  Output formats: {', '.join(wf['output_formats'])}")
                    
            formatted.append("")  # 添加空行分隔
        
        if output_full:
            return formatted
        else:
            return "\n".join(formatted)

async def main():
    """Dockstore 工作流搜索工具
    
    用法:
    1. 多条件搜索:
       python dockstore_search.py -q "term1" "field1" "operator1" -q "term2" "field2" "operator2"
    """
    parser = argparse.ArgumentParser(description='Dockstore 工作流搜索工具')
    
    # 查询参数
    parser.add_argument('-q', '--query', 
                       action='append', 
                       nargs=3,
                       metavar=('TERM', 'FIELD', 'OPERATOR'),
                       help='查询参数：搜索词 搜索字段 布尔操作符(AND/OR), 可多次使用')
    
    # 可选参数
    parser.add_argument('-t', '--type',
                       choices=['match_phrase', 'wildcard'],
                       default='match_phrase',
                       help='查询类型: match_phrase (默认) 或 wildcard')
    parser.add_argument('--sentence',
                       action='store_true',
                       help='将搜索词作为完整句子处理')
    parser.add_argument('--outputfull',
                       action='store_true',
                       help='显示完整工作流信息')
    parser.add_argument('--descriptor-type',
                       choices=['WDL', 'CWL', 'NFL'],
                       help='只返回指定描述符类型的工作流')
    parser.add_argument('--verified-only',
                       action='store_true',
                       help='只返回已验证的工作流')
    parser.add_argument('--include-archived',
                       action='store_true',
                       help='包含已归档的工作流')
    
    args = parser.parse_args()
    client = DockstoreSearch()
    
    try:
        # 从多个 -q 参数构建查询
        queries = []
        if args.query:
            for term, field, operator in args.query:
                queries.append({
                    "terms": [term],
                    "fields": [field],
                    "operator": operator.upper(),
                    "query_type": args.type
                })
        
        if not queries:
            print("请使用 -q 选项指定搜索条件")
            return
            
        # 执行搜索
        results = await client.search(
            queries, 
            args.sentence, 
            args.type,
            args.descriptor_type,  # 新增
            args.verified_only,    # 新增
            args.include_archived  # 新增
        )
        
        if not results or "hits" not in results or not results["hits"].get("hits"):
            print("未找到相关工作流")
            return
            
        # 显示搜索结果
        print(client.format_results(results, args.outputfull))
        
        # 保存搜索结果
        result_path = os.path.abspath('dockstore_results.json')
        with open(result_path, 'w', encoding='utf-8') as f:
            json.dump(results, f, indent=2, ensure_ascii=False)
        #print(f"\n结果文件已保存到: {result_path}")
            
    except Exception as e:
        print(f"执行出错: {str(e)}")

if __name__ == "__main__":
    asyncio.run(main())