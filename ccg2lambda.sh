#!/bin/bash
#
#  Copyright 2016 Pascual Martinez-Gomez
#
#  Licensed under the Apache License, Version 2.0 (the "License");
#  you may not use this file except in compliance with the License.
#  You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
#  Unless required by applicable law or agreed to in writing, software
#  distributed under the License is distributed on an "AS IS" BASIS,
#  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#  See the License for the specific language governing permissions and
#  limitations under the License.

# Script to Recognize Textual Entailment of problems in English, using
# multiple CCG parsers (C&C and EasyCCG at the moment).
# This script receives a file with several sentences (one per line), where all
# sentences are premises except the last one, which is a conclusion. It returns
# 'yes' (the premises entail the conclusion), 'no' (there is a contradiction) or
# 'unknown' (none of the former).
# You can use it as:
# 
# ./rte_en_mp_any.sh <sentences.txt> <semantic_templates.yaml> <nbest>
# 
# E.g.
# ./rte_en_mp_any.sh en/sample_en.txt en/semantic_templates_en.yaml 3

USAGE="Usage: ./ccg2lambda.sh <sentences.txt> <semantic_templates.yaml> <nbest>"

# Set the number of nbest parses (Default: 1)
nbest=${3:-1}

# Create a file named "parser_location.txt" at the "en" directory and
# write a list of CCG parsers installed, as in:
# $ cat en/parser_location.txt
# candc:/path/to/candc-1.00
# easyccg:/path/to/easyccg
# easysrl:/path/to/EasySRL
# depccg:/path/to/depccg

# # Check that the number of arguments is correct.
# if [ "$#" -ne 2 ]; then
#   echo "Error: Number of arguments invalid".
#   echo $USAGE
#   exit 1
# fi

# This variable contains the filename where the category templates are.
category_templates=$2
if [ ! -f $category_templates ]; then
  echo "Error: File with semantic templates does not exist."
  echo $USAGE
  exit 1
fi

# This variable contains the name of the dataset (fracas or jsem).
sentences_fname=$1
sentences_basename=${sentences_fname##*/}
if [ ! -f $sentences_fname ]; then
  echo "Error: File with plain sentences does not exist."
  echo $USAGE
  exit 1
fi

function timeout() { perl -e 'alarm shift; exec @ARGV' "$@"; }

# These variables contain the names of the directories where intermediate
# results will be written.
plain_dir="en_plain" # tokenized sentences.
parsed_dir="en_parsed" # parsed sentences into XML or other formats.
results_dir="en_results" # HTML semantic outputs, proving results, etc.
rm -rf  $parsed_dir $results_dir
mkdir -p $plain_dir $parsed_dir $results_dir

# Tokenize text with Penn Treebank tokenizer.
cat $sentences_fname | \
  sed -f en/tokenizer.sed | \
  sed 's/ _ /_/g' | \
  sed 's/[[:space:]]*$//' \
  > ${plain_dir}/${sentences_basename}.tok


# Set parser locations
if [ ! -f "en/parser_location.txt" ]; then
  echo "Error: File for the locations of parsers does not exist."
  exit 1
fi
for parser in `cat en/parser_location.txt`; do
  parser_name=`echo $parser | awk -F':' '{print $1}'`
  parser_dir=`echo $parser | awk -F':' '{print $2}'`
  if [ "${parser_name}" == "candc" ]; then
    candc_dir=${parser_dir}
    if [ ! -d "${candc_dir}" ] || [ ! -e "${candc_dir}"/bin/candc ]; then
      echo "C&C parser directory incorrect. Exit."
      exit 1
    fi
  fi
  if [ "${parser_name}" == "depccg" ]; then
    depccg_exists=`pip freeze | grep depccg`
    if [ "${depccg_exists}" == "" ]; then
      echo "depccg parser directory incorrect. Exit."
      exit 1
    fi
  fi
done

function parse_depccg() {
    # Parse using depccg.
    base_fname=$1
    cat ${plain_dir}/${base_fname}.tok | \
    env CANDC=${candc_dir} depccg_en \
        --model elmo \
        --input-format raw \
        --annotator candc \
        --format jigg_xml \
        --nbest $nbest \
        --root-cats 'NP' \
    > ${parsed_dir}/${base_fname}.depccg.jigg.xml \
    2> ${parsed_dir}/${base_fname}.log
}

function semantic_parsing() {
  parser=$1
  sentences_basename=$2
  python scripts/semparse.py \
    $parsed_dir/${sentences_basename}.${parser}.jigg.xml \
    $category_templates \
    $parsed_dir/${sentences_basename}.${parser}.sem.xml \
    --arbi-types \
    2> $parsed_dir/${sentences_basename}.${parser}.sem.err
}


# CCG parsing, semantic parsing and theorem proving

if [ ! -e ${parsed_dir}/${sentences_basename}.${parser_name}.jigg.xml ]; then
  echo "${parser_name} parsing ${plain_dir}/${sentences_basename}"
  parse_$parser_name $sentences_basename
fi

if [ ! -e ${parsed_dir}/${sentences_basename}.${parser_name}.sem.xml ]; then
  echo "semantic parsing $parsed_dir/${sentences_basename}.${parser_name}.sem.xml"
  semantic_parsing $parser_name $sentences_basename 
fi

#python scripts/stl_json.py ${parsed_dir}/${sentences_basename}.${parser_name}.sem.xml \
#> ${results_dir}/${sentences_basename}.STL.json

python scripts/visualize.py ${parsed_dir}/${sentences_basename}.${parser_name}.sem.xml \
> ${results_dir}/${sentences_basename}.${parser_name}.html


