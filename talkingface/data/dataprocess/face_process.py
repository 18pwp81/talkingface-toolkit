import sys

# 检查Python版本是否符合要求
if sys.version_info[0] < 3 and sys.version_info[1] < 2:
    raise Exception("Must be using >= Python 3.2")
from os import listdir, path

if not path.isfile('../../utils/face_detection/detection/sfd/s3fd.pth'):
    raise FileNotFoundError('Save the s3fd model to face_detection/detection/sfd/s3fd.pth \
							before running this script!')
import multiprocessing as mp
import numpy as np
import argparse, os, cv2, traceback, subprocess
from tqdm import tqdm
from glob import glob
import audio_process
import talkingface.utils.face_detection as face_detection
import mediapipe as mp
import math
import shutil

parent_folder = os.path.abspath(os.path.join(os.getcwd(), os.pardir, os.pardir, os.pardir))
data_path = os.path.join(parent_folder, "dataset", "MEAD", "data")
preprocessed_path = os.path.join(parent_folder, "dataset", "MEAD", "preprocessed_data")

# 设置命令行参数
parser = argparse.ArgumentParser()
parser.add_argument('--batch_size', help='Single GPU Face detection batch size', default=1, type=int)
"""LRS2 data preprocess"""
parser.add_argument("--origin_data_root", help="Root folder of the dataset", default=data_path)
parser.add_argument("--clip_flag", help="Flag for cliping video into 5s", default=0, type=int)
parser.add_argument('--Function', type=str, help='Choosing base or HR', default="base")
parser.add_argument("--hyperlips_train_dataset", help="Root folder of the preprocessed dataset", default=preprocessed_path)
parser.add_argument("--hyperlipsbase_video_root", help="Root folder of the videos generated by hyper_base",
                    default="results")
parser.add_argument('--gpu_id', type=float, help='gpu id (default: 0)', default=0, required=False)
args = parser.parse_args()

# face_detector
# 定义了一系列人脸的关键点集合
# 这些关键点集合描述了人脸的不同部分，如嘴唇、眼睛、眉毛、鼻子等
# 这些关键点集合被用来标识人脸的不同区域
fa = face_detection.FaceAlignment(face_detection.LandmarksType._2D, flip_input=False,
                                  device='cuda:{}'.format(args.gpu_id))

template = 'ffmpeg -loglevel panic -y -i {} -strict -2 {}'

mp_drawing = mp.solutions.drawing_utils
mp_drawing_styles = mp.solutions.drawing_styles
mp_face_mesh = mp.solutions.face_mesh
lip_index = [164, 167, 165, 92, 186, 57, 43, 106, 182, 83, 18, 313, 406, 335, 273, 287, 410, 322, 391, 393]
FACEMESH_LIPS = frozenset([(61, 146), (146, 91), (91, 181), (181, 84), (84, 17),
                           (17, 314), (314, 405), (405, 321), (321, 375),
                           (375, 291), (61, 185), (185, 40), (40, 39), (39, 37),
                           (37, 0), (0, 267),
                           (267, 269), (269, 270), (270, 409), (409, 291),
                           (78, 95), (95, 88), (88, 178), (178, 87), (87, 14),
                           (14, 317), (317, 402), (402, 318), (318, 324),
                           (324, 308), (78, 191), (191, 80), (80, 81), (81, 82),
                           (82, 13), (13, 312), (312, 311), (311, 310),
                           (310, 415), (415, 308)])

FACEMESH_LEFT_EYE = frozenset([(263, 249), (249, 390), (390, 373), (373, 374),
                               (374, 380), (380, 381), (381, 382), (382, 362),
                               (263, 466), (466, 388), (388, 387), (387, 386),
                               (386, 385), (385, 384), (384, 398), (398, 362)])

FACEMESH_LEFT_IRIS = frozenset([(474, 475), (475, 476), (476, 477),
                                (477, 474)])

FACEMESH_LEFT_EYEBROW = frozenset([(276, 283), (283, 282), (282, 295),
                                   (295, 285), (300, 293), (293, 334),
                                   (334, 296), (296, 336)])

FACEMESH_RIGHT_EYE = frozenset([(33, 7), (7, 163), (163, 144), (144, 145),
                                (145, 153), (153, 154), (154, 155), (155, 133),
                                (33, 246), (246, 161), (161, 160), (160, 159),
                                (159, 158), (158, 157), (157, 173), (173, 133)])

FACEMESH_RIGHT_EYEBROW = frozenset([(46, 53), (53, 52), (52, 65), (65, 55),
                                    (70, 63), (63, 105), (105, 66), (66, 107)])

FACEMESH_RIGHT_IRIS = frozenset([(469, 470), (470, 471), (471, 472),
                                 (472, 469)])

FACEMESH_FACE_OVAL = frozenset([(389, 356), (356, 454),
                                (454, 323), (323, 361), (361, 288), (288, 397),
                                (397, 365), (365, 379), (379, 378), (378, 400),
                                (400, 377), (377, 152), (152, 148), (148, 176),
                                (176, 149), (149, 150), (150, 136), (136, 172),
                                (172, 58), (58, 132), (132, 93), (93, 234),
                                (234, 127), (127, 162)])

FACEMESH_NOSE = frozenset([(168, 6), (6, 197), (197, 195), (195, 5), (5, 4),
                           (4, 45), (45, 220), (220, 115), (115, 48),
                           (4, 275), (275, 440), (440, 344), (344, 278), ])

# 在后续的处理中用于选择感兴趣的区域（ROI，Region of Interest），以便在人脸处理过程中专注于特定区域
ROI = frozenset().union(*[FACEMESH_LIPS, FACEMESH_LEFT_EYE, FACEMESH_LEFT_EYEBROW,
                          FACEMESH_RIGHT_EYE, FACEMESH_RIGHT_EYEBROW, FACEMESH_FACE_OVAL, FACEMESH_NOSE])


def split_video_5s(args):
    """
        将输入视频分割成5秒的片段并保存。

        参数:
            args (argparse.Namespace): 包含 origin_data_root、hyperlips_train_dataset 等命令行参数的命名空间。

        返回:
            无
    """
    print("Starting to divide videos")
    # 获取输入路径中的视频文件列表
    path = args.origin_data_root
    video_list = os.listdir(path)

    # 创建保存视频片段的目录
    save_path = os.path.join(args.hyperlips_train_dataset, "video_clips", path.split("/")[-1])
    os.makedirs(save_path, exist_ok=True)
    # 定义每个片段的时长（5秒）
    delta_X = 5

    mark = 0

    # 使用 ffprobe 获取视频文件的长度（时长）的函数
    def get_length(filename):
        result = subprocess.run(["ffprobe", "-v", "error", "-show_entries",
                                 "format=duration", "-of",
                                 "default=noprint_wrappers=1:nokey=1", filename],
                                stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT)
        return float(result.stdout)

    # 遍历每个视频文件
    for file_name in video_list:
        # 获取视频的总时长，单位为分钟和秒
        min = int(get_length(os.path.join(path, file_name))) // 60
        second = int(get_length(os.path.join(path, file_name))) % 60
        # 为输出视频片段名称定义前缀
        video_name = str(file_name.split('.mp4')[0] + 'video_')

        # 遍历每分钟的视频
        for i in range(min + 1):
            # 检查视频中是否有足够的时间创建一个5秒的片段
            if (second + min * 60) >= delta_X:
                start_time = 0
                end_time = start_time + delta_X

                # 遍历5秒片段的每一秒
                for j in range((second) + 1):
                    min_temp = str(i)
                    start = str(start_time)
                    end = str(end_time)
                    # 添加前导零以确保正确的格式
                    if len(str(min_temp)) == 1:
                        min_temp = '0' + str(min_temp)
                    if len(str(start_time)) == 1:
                        start = '0' + str(start_time)
                    if len(str(end_time)) == 1:
                        end = '0' + str(end_time)

                    # 为视频片段创建唯一标识符
                    if len(str(mark)) < 6:
                        name = '0' * (6 - len(str(mark)) - 1) + str(mark)
                    else:
                        name = str(mark)

                    # 生成提取5秒片段的 ffmpeg 命令
                    command = 'ffmpeg -i {} -ss 00:{}:{} -to 00:{}:{} -strict -2 -ar 16000 -r 25 -qscale 0.001 {}'.format(
                        os.path.join(path, file_name),
                        min_temp, start, min_temp, end,
                        os.path.join(save_path,
                                     video_name + 'id' + str(name)) + '.mp4')  # -c:v copy -c:a copy -b:v 0 -q:v 1
                    print(command)

                    # 执行 ffmpeg 命令以创建视频片段
                    mark += 1
                    os.system(command)
                    # 为下一个5秒片段更新 start_time 和 end_time
                    if i != min or (i == min and (end_time + delta_X) < second):
                        start_time += delta_X
                        end_time += delta_X
                    elif (end_time + delta_X) <= second:
                        start_time += delta_X
                        end_time += delta_X
                    elif (end_time + delta_X) > second:
                        break


def get_sketch(hight, width, image, savepath):
    """
        生成人脸轮廓图像并保存。

        参数:
            hight (int): 输入图像的高度。
            width (int): 输入图像的宽度。
            image (numpy.ndarray): 输入图像的像素数组。
            savepath (str): 要保存生成轮廓图像的路径。

        返回:
            无
    """
    with mp_face_mesh.FaceMesh(
            max_num_faces=1,
            refine_landmarks=True,
            min_detection_confidence=0.5,
            min_tracking_confidence=0.5) as face_mesh:

        results = face_mesh.process(image)
        if results.multi_face_landmarks == None:
            print("no sketch:" + savepath)
        else:
            face_landmarks = results.multi_face_landmarks[0]
            output = np.zeros((hight, width, 3), np.uint8)
            mp_drawing.draw_landmarks(
                image=output,
                landmark_list=face_landmarks,
                connections=ROI,
                landmark_drawing_spec=None,
                connection_drawing_spec=mp_drawing.DrawingSpec(thickness=6, circle_radius=1, color=(255, 255, 255))
            )
            cv2.imwrite(savepath, output)


def get_landmarks(image, face_mesh, hight, width):
    """
        获取图像中人脸的关键点坐标。

        参数:
            image (numpy.ndarray): 输入图像的像素数组。
            face_mesh (mp_face_mesh.FaceMesh): MediaPipe FaceMesh 模型。
            hight (int): 输入图像的高度。
            width (int): 输入图像的宽度。

        返回:
            list: 包含人脸关键点坐标的列表。
    """
    landmarks = []
    results = face_mesh.process(cv2.cvtColor(image, cv2.COLOR_BGR2RGB))
    if results.multi_face_landmarks:
        for face_landmarks in results.multi_face_landmarks:
            i = 0
            points = {}
            for landmark in face_landmarks.landmark:
                x = math.floor(landmark.x * width)
                y = math.floor(landmark.y * hight)
                points[i] = (x, y)
                i += 1
            landmarks.append(points)
    return landmarks


def get_mask(hight, width, image, savepath):
    """
        生成唇部遮罩图像并保存。

        参数:
            hight (int): 输入图像的高度。
            width (int): 输入图像的宽度。
            image (numpy.ndarray): 输入图像的像素数组。
            savepath (str): 要保存生成遮罩图像的路径。

        返回:
            无
    """
    with mp_face_mesh.FaceMesh(
            max_num_faces=1,
            refine_landmarks=True,
            min_detection_confidence=0.5,
            min_tracking_confidence=0.5) as face_mesh:

        face_landmark = get_landmarks(image, face_mesh, hight, width)
        if face_landmark == []:
            print("no mask:" + savepath)
        else:
            lip_landmark = []
            for i in lip_index:
                lip_landmark.append(face_landmark[0][i])
            lip_landmark = np.array(lip_landmark)
            points = lip_landmark.reshape(-1, 1, 2).astype(np.int32)
            matrix = np.zeros((hight, width), dtype=np.int32)
            cv2.drawContours(matrix, [points], -1, (1), thickness=-1)
            list_of_points_indices = np.nonzero(matrix)
            mask = np.zeros((hight, width), np.uint8)
            mask[list_of_points_indices] = 255
            cv2.imwrite(savepath, mask)


def data_process_hyper_base(args):
    """
    预处理函数，生成用于训练的数据集。

    参数:
        args (argparse.Namespace): 命令行参数的命名空间。

    返回:
        无
    """
    # 如果 clip_flag 参数为 0，表示需要从原始数据中复制视频文件到指定目录
    if args.clip_flag == 0:
        # 获取原始数据目录下所有 .mp4 格式的文件列表
        filelist = glob(os.path.join(args.origin_data_root, '*.mp4'))
        # 创建保存视频剪辑的目录
        save_dir = os.path.join(args.hyperlips_train_dataset, 'video_clips')
        os.makedirs(save_dir, exist_ok=True)

        # 遍历原始数据文件列表，复制视频文件到指定目录
        for video in filelist:
            dirname, filename = os.path.split(video)
            relative_path = os.path.relpath(video, args.origin_data_root)
            save_path = os.path.join(args.hyperlips_train_dataset, 'video_clips', relative_path)
            print(save_path)
            os.makedirs(os.path.dirname(save_path), exist_ok=True)
            shutil.copy(video, save_path)

    # 获取视频剪辑目录下所有子目录中的 .mp4 文件列表
    # filelist = glob(os.path.join(args.hyperlips_train_dataset, "video_clips", '*/*.mp4'))
    filelist = glob(os.path.join(args.hyperlips_train_dataset, "video_clips", '*.mp4'))
    filelist_new = []

    # 将文件路径中的反斜杠替换为正斜杠
    for i in filelist:
        res = i.replace('\\', '/')
        filelist_new.append(res)

    # 遍历新的文件列表
    for i in tqdm(range(len(filelist_new))):
        # 获取当前视频文件的路径
        vfile = filelist_new[i]
        # 读取视频流并提取帧
        video_stream = cv2.VideoCapture(vfile)
        frames = []
        while 1:
            still_reading, frame = video_stream.read()
            if not still_reading:
                video_stream.release()
                break
            frames.append(frame)

        # 获取视频文件名和所在目录名
        vidname = os.path.basename(vfile).split('.')[0]
        dirname = vfile.split('/')[-2]

        # 构建保存图片的目录路径
        fulldir = path.join(args.hyperlips_train_dataset, "imgs", vidname)
        os.makedirs(fulldir, exist_ok=True)

        # 将帧划分为批次进行处理
        batches = [frames[i:i + args.batch_size] for i in range(0, len(frames), args.batch_size)]
        i = -1
        for fb in batches:
            # 使用 face_alignment 模型获取人脸框坐标
            preds = fa.get_detections_for_batch(np.asarray(fb))

            for j, f in enumerate(preds):
                i += 1
                # 如果人脸框坐标为 None，输出错误信息并继续下一帧
                if f is None:
                    print(vfile + " is wrong")
                    continue
                x1, y1, x2, y2 = f
                # 保存人脸区域为图片文件
                cv2.imwrite(path.join(fulldir, '{}.jpg'.format(i)), fb[j][y1:y2, x1:x2])

        # 构建保存音频文件的路径
        wavpath = path.join(fulldir, 'audio.wav')
        # 使用 ffmpeg 命令从视频中提取音频并保存
        command = template.format(vfile, wavpath)
        subprocess.call(command, shell=True)


def split_train_test_text(args):
    """
    将视频划分为训练集和验证集，并将视频名称存储到相应的文本文件中。

    参数:
        args (argparse.Namespace): 命令行参数的命名空间。

    返回:
        无
    """
    # 构建保存图片的目录路径
    path = os.path.join(args.hyperlips_train_dataset, "imgs")
    # 定义训练集和验证集的文本文件路径
    train_txt = '../../../dataset/MEAD/filelist/train.txt'
    val_txt = '../../../dataset/MEAD/filelist/val.txt'
    # 创建保存训练集和验证集文本文件的目录
    os.makedirs(train_txt.split('/')[-2], exist_ok=True)

    # 导入必要的库
    import random
    import shutil
    # 获取所有视频的列表
    video_list = os.listdir(path)

    # 获取所有图片的列表
    list1 = glob(os.path.join(path, "*/*"))
    # 计算验证集的数量
    extor_cout = int(len(list1) * 0.1)
    extor_list = []

    # 从图片列表中随机选择一定数量的图片作为验证集
    for cout in range(0, extor_cout):
        val_single = random.choice(list1)
        print(val_single)
        # 构建验证集图片的相对路径
        # val_single = os.path.join(val_single.split('/')[-2], val_single.split('/')[-1])
        val_single = os.path.join(val_single.split('\\')[-2], val_single.split('\\')[-1])
        extor_list.append(val_single)

    # 分别打开训练集和验证集的文本文件进行写入
    with open(train_txt, 'w') as f:
        with open(val_txt, 'w') as f1:
            # 遍历所有视频
            for item in video_list:
                path2 = (path) + '/' + item
                video_list2 = os.listdir(path2)
                # 遍历每个视频的图片
                for vilist2 in video_list2:
                    # item2 = item + '/' + vilist2
                    item2 = os.path.join(item, vilist2)
                    # 将图片的相对路径写入训练集或验证集文件
                    if item2 not in extor_list:
                        f.write(item2)
                        f.write('\n')
                    else:
                        f1.write(item2)
                        f1.write('\n')


def data_process_hyper_hq_module(args):
    """
    对高质量数据进行处理，生成用于训练HyperLips的高分辨率数据集。

    参数:
        args (argparse.Namespace): 命令行参数的命名空间。

    返回:
        无
    """
    # 获取所有高质量视频文件的路径
    filelist = glob(path.join(args.hyperlipsbase_video_root, '*/*.mp4'))
    filelist_new = []
    # 构建高分辨率训练数据集的根目录
    hyperlipsHR_train_dataset = os.path.join(args.hyperlips_train_dataset, "HR_Train_Dateset")
    os.makedirs(hyperlipsHR_train_dataset, exist_ok=True)

    # 转换路径分隔符，并将路径添加到新的列表中
    for i in filelist:
        res = i.replace('\\', '/')
        filelist_new.append(res)
    print(filelist_new)
    for i in tqdm(range(len(filelist_new))):
        vfile_h = filelist_new[i]
        vidname = os.path.basename(vfile_h).split('.')[0]
        dirname = vfile_h.split('/')[-2]

        # 构建原始数据和HyperLips训练数据的视频文件路径
        vfile_o = path.join(args.hyperlips_train_dataset, "video_clips", (args.origin_data_root.split("\\")[-1]),
                            vidname + ".mp4")

        # 构建高分辨率训练数据集的子目录
        fulldir_origin_data_img = path.join(hyperlipsHR_train_dataset, 'GT_IMG', dirname, vidname)
        os.makedirs(fulldir_origin_data_img, exist_ok=True)
        fulldir_hyper_img = path.join(hyperlipsHR_train_dataset, 'HYPER_IMG', dirname, vidname)
        os.makedirs(fulldir_hyper_img, exist_ok=True)
        fulldir_origin_mask = path.join(hyperlipsHR_train_dataset, 'GT_MASK', dirname, vidname)
        os.makedirs(fulldir_origin_mask, exist_ok=True)
        fulldir_origin_sketch = path.join(hyperlipsHR_train_dataset, 'GT_SKETCH', dirname, vidname)
        os.makedirs(fulldir_origin_sketch, exist_ok=True)
        fulldir_hyper_sketch = path.join(hyperlipsHR_train_dataset, 'HYPER_SKETCH', dirname, vidname)
        os.makedirs(fulldir_hyper_sketch, exist_ok=True)

        # 读取高质量视频的帧
        video_stream_h = cv2.VideoCapture(vfile_h)
        video_stream_o = cv2.VideoCapture(vfile_o)
        frames_h = []
        frames_o = []
        while 1:
            still_reading_o, frame_o = video_stream_o.read()
            still_reading_h, frame_h = video_stream_h.read()
            if not still_reading_h:
                video_stream_h.release()
                video_stream_o.release()
                break
            frames_h.append(frame_h)
            frames_o.append(frame_o)

        # 划分帧为小批次
        batches_h = [frames_h[i:i + args.batch_size] for i in range(0, len(frames_h), args.batch_size)]
        batches_o = [frames_o[i:i + args.batch_size] for i in range(0, len(frames_o), args.batch_size)]
        num = -1

        # 遍历每个小批次
        for i in range(len(batches_h)):
            f_o = batches_o[i]
            f_h = batches_h[i]
            preds = fa.get_detections_for_batch(np.asarray(batches_h[i]))

            # 遍历每帧
            for j, f in enumerate(preds):
                num += 1
                if f is None:
                    continue
                x1, y1, x2, y2 = f

                # 保存原始数据和HyperLips训练数据的图片
                cv2.imwrite(path.join(fulldir_origin_data_img, '{}.jpg'.format(num)), f_o[j][y1:y2, x1:x2])
                cv2.imwrite(path.join(fulldir_hyper_img, '{}.jpg'.format(num)), f_h[j][y1:y2, x1:x2])

                # 计算口罩区域的高度和宽度，并保存原始数据的口罩掩码
                hight = y2 - y1
                width = x2 - x1
                savepath_origin_mask = path.join(fulldir_origin_mask, '{}.jpg'.format(num))
                get_mask(hight, width, f_o[j][y1:y2, x1:x2], savepath_origin_mask)

                # 保存原始数据和HyperLips训练数据的口罩轮廓
                savepath_origin_sketch = path.join(fulldir_origin_sketch, '{}.jpg'.format(num))
                get_sketch(hight, width, f_o[j][y1:y2, x1:x2], savepath_origin_sketch)
                savepath_hyper_sketch = path.join(fulldir_hyper_sketch, '{}.jpg'.format(num))
                get_sketch(hight, width, f_h[j][y1:y2, x1:x2], savepath_hyper_sketch)


if __name__ == '__main__':

    if args.Function == 'base':
        print("Starting to generate hyperlipsbase train dataset...")

        " Dividing the videos into 5s segments"
        # 如果设置了clip_flag，进行视频分割
        if args.clip_flag == 1:
            print("Starting to divid the videos")
            split_video_5s(args)
        " Generating train data for hyper_base"
        data_process_hyper_base(args)
        " Generating filelists for train and val"
        # 生成训练和验证集的文件列表
        split_train_test_text(args)
    elif args.Function == 'HR':
        print("Starting to generate hyperlipsHR train dataset...")
        # 生成hyperlipsHR的训练数据
        data_process_hyper_hq_module(args)
    else:
        print("Please choose the right function!")