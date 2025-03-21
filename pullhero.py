#!/usr/bin/env python3
# GNU GENERAL PUBLIC LICENSE
# Version 3, 29 June 2007
#
# Copyright (C) 2025 authors
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program. If not, see <https://www.gnu.org/licenses/>.

import os
import json
import logging
import argparse
import requests
import sys
from github import Github
from gitingest import ingest
import pygit2

def setup_logging():
    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s - %(levelname)s - %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)],
    )

def clone_repo_with_token(repo_url, local_path, github_token):
    def credentials_callback(url, username_from_url, allowed_types):
        if github_token:
            return pygit2.UserPass("x-access-token", github_token)
        else:
            raise ValueError("GITHUB_TOKEN is not set")
    try:
        logging.info(f"Cloning repository from {repo_url} to {local_path}")
        remote_callbacks = pygit2.RemoteCallbacks(credentials=credentials_callback)
        pygit2.clone_repository(repo_url, local_path, callbacks=remote_callbacks)
        logging.info(f"Repository cloned to {local_path}")
        # Listing recursively
        logging.info("Listing files from the cloned repository:")
        for root, dirs, files in os.walk(local_path):
            for file in files:
                logging.info(os.path.join(root, file))
    except Exception as e:
        logging.error(f"Error cloning the repository: {e}")
        raise

def get_issues_with_label(github_token, owner, repo, label):
    url = f"https://api.github.com/repos/{owner}/{repo}/issues?labels={label}"
    headers = {"Authorization": f"Bearer {github_token}"}
    response = requests.get(url, headers=headers)
    response.raise_for_status()
    return response.json()

def get_issue_comments(github_token, issue_url):
    headers = {"Authorization": f"Bearer {github_token}"}
    response = requests.get(f"{issue_url}/comments", headers=headers)
    response.raise_for_status()
    return response.json()

def remove_label_from_issue(github_token, owner, repo, issue_number, label):
    url = f"https://api.github.com/repos/{owner}/{repo}/issues/{issue_number}/labels/{label}"
    headers = {"Authorization": f"Bearer {github_token}"}
    response = requests.delete(url, headers=headers)
    if response.status_code == 200 or response.status_code == 204:
        logging.info(f"Label '{label}' removed from issue #{issue_number}")
    else:
        logging.error(f"Failed to remove label '{label}' from issue #{issue_number}: {response.text}")

def call_ai_api(api_host, api_key, api_model, prompt):
    url = f"https://{api_host}/v1/chat/completions"
    payload = {"model": api_model, "messages": [{"role": "user", "content": prompt}], "max_tokens": 1000}
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    response = requests.post(url, json=payload, headers=headers)
    response.raise_for_status()
    return response.json()["choices"][0]["message"]["content"]

def main():
    setup_logging()
    parser = argparse.ArgumentParser(description='Process GitHub issues with consult label.')
    parser.add_argument('--github-token', default=os.environ.get('GITHUB_TOKEN'), help='GitHub Token')
    parser.add_argument('--api-key', default=os.environ.get('LLM_API_KEY'), help='AI API Key')
    parser.add_argument('--api-host', default=os.environ.get('LLM_API_HOST', 'api.openai.com'), help='LLM API HOST')
    parser.add_argument('--api-model', default=os.environ.get('LLM_API_MODEL', 'gpt-4o-mini'), help='LLM Model')
    args = parser.parse_args()
    
    repo_name = os.environ['GITHUB_REPOSITORY']
    owner, repo = repo_name.split('/')

    local_repo_path = "/tmp/clone"
    repo_url = f"https://github.com/{owner}/{repo}.git"
    clone_repo_with_token(repo_url, local_repo_path, args.github_token)

    summary, tree, content = ingest(f"{local_repo_path}")
    logging.info(f"Summary: '{summary}'")

    issues = get_issues_with_label(args.github_token, owner, repo, "consult")
    g = Github(args.github_token)
    repo_obj = g.get_repo(f"{owner}/{repo}")
    
    for issue in issues:
        issue_comments = get_issue_comments(args.github_token, issue["url"])
        comments_text = "\n".join([c["body"] for c in issue_comments])
        prompt = f"""Consultation Task:
Summary:
{summary}

Tree:
{tree}

Content:
{content}

Issue:
{issue["title"]}

Description:
{issue["body"]}

Comments:
{comments_text}

Instructions:
1. Answer the questions or concerns in the issue.
2. Include in the analysis the comments if needed.
3. Provide a detailed and helpful response.
4. Use the repository Summary, Tree, and Content as context.
5. Format the output in Markdown format.
"""
        try:
            response_text = call_ai_api(args.api_host, args.api_key, args.api_model, prompt)
        except Exception as e:
            logging.error(f"AI API call failed: {e}")
            continue
        issue_obj = repo_obj.get_issue(issue["number"])
        issue_obj.create_comment(response_text)
        logging.info(f"Response posted to issue #{issue['number']}")

        remove_label_from_issue(args.github_token, owner, repo, issue["number"], "consult")

if __name__ == "__main__":
    main()
