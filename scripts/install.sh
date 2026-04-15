# tar -czf quant-ai.tar.gz quant-ai/ \
#   --exclude='venv' \
#   --exclude='__pycache__' \
#   --exclude='.DS_Store'

tar -xzf quant-ai.tar.gz
# 4. 创建虚拟环境并安装依赖
cd quant-ai
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
# 5. 配置 .env（注意修改 Tushare API Key）
cp .env.example .env
nohup python main.py > output.log 2>&1 &